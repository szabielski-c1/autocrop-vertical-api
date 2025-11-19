import time
import cv2
import subprocess
import os
import numpy as np
from tqdm import tqdm
from scenedetect import VideoManager, SceneManager
from scenedetect.detectors import ContentDetector
from ultralytics import YOLO

# --- Constants ---
ASPECT_RATIO = 9 / 16

# Load models once
model = YOLO('yolov8n.pt')
face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')


def analyze_scene_content(video_path, scene_start_time, scene_end_time):
    """Analyzes the middle frame of a scene to detect people and faces."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return []

    start_frame = scene_start_time.get_frames()
    end_frame = scene_end_time.get_frames()
    middle_frame_number = int(start_frame + (end_frame - start_frame) / 2)

    cap.set(cv2.CAP_PROP_POS_FRAMES, middle_frame_number)
    ret, frame = cap.read()
    if not ret:
        cap.release()
        return []

    results = model([frame], verbose=False)
    detected_objects = []

    for result in results:
        boxes = result.boxes
        for box in boxes:
            if box.cls[0] == 0:
                x1, y1, x2, y2 = [int(i) for i in box.xyxy[0]]
                person_box = [x1, y1, x2, y2]

                person_roi_gray = cv2.cvtColor(frame[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
                faces = face_cascade.detectMultiScale(person_roi_gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))

                face_box = None
                if len(faces) > 0:
                    fx, fy, fw, fh = faces[0]
                    face_box = [x1 + fx, y1 + fy, x1 + fx + fw, y1 + fy + fh]

                detected_objects.append({'person_box': person_box, 'face_box': face_box})

    cap.release()
    return detected_objects


def detect_scenes(video_path):
    video_manager = VideoManager([video_path])
    scene_manager = SceneManager()
    scene_manager.add_detector(ContentDetector())
    video_manager.set_downscale_factor()
    video_manager.start()
    scene_manager.detect_scenes(frame_source=video_manager)
    scene_list = scene_manager.get_scene_list()
    fps = video_manager.get_framerate()
    video_manager.release()
    return scene_list, fps


def get_enclosing_box(boxes):
    if not boxes:
        return None
    min_x = min(box[0] for box in boxes)
    min_y = min(box[1] for box in boxes)
    max_x = max(box[2] for box in boxes)
    max_y = max(box[3] for box in boxes)
    return [min_x, min_y, max_x, max_y]


def decide_cropping_strategy(scene_analysis, frame_height):
    num_people = len(scene_analysis)
    if num_people == 0:
        return 'LETTERBOX', None
    if num_people == 1:
        target_box = scene_analysis[0]['face_box'] or scene_analysis[0]['person_box']
        return 'TRACK', target_box
    person_boxes = [obj['person_box'] for obj in scene_analysis]
    group_box = get_enclosing_box(person_boxes)
    group_width = group_box[2] - group_box[0]
    max_width_for_crop = frame_height * ASPECT_RATIO
    if group_width < max_width_for_crop:
        return 'TRACK', group_box
    else:
        return 'LETTERBOX', None


def calculate_crop_box(target_box, frame_width, frame_height):
    target_center_x = (target_box[0] + target_box[2]) / 2
    crop_height = frame_height
    crop_width = int(crop_height * ASPECT_RATIO)
    x1 = int(target_center_x - crop_width / 2)
    y1 = 0
    x2 = int(target_center_x + crop_width / 2)
    y2 = frame_height
    if x1 < 0:
        x1 = 0
        x2 = crop_width
    if x2 > frame_width:
        x2 = frame_width
        x1 = frame_width - crop_width
    return x1, y1, x2, y2


def get_video_resolution(video_path):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise IOError(f"Could not open video file {video_path}")
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    return width, height


def process_video(input_video: str, output_video: str, progress_callback=None) -> dict:
    """
    Process a video from horizontal to vertical format.

    Args:
        input_video: Path to input video file
        output_video: Path to output video file
        progress_callback: Optional callback function(step, progress, message)

    Returns:
        dict with processing results
    """
    start_time = time.time()

    # Define temporary file paths
    base_name = os.path.splitext(output_video)[0]
    temp_video_output = f"{base_name}_temp_video.mp4"
    temp_audio_output = f"{base_name}_temp_audio.aac"

    # Clean up previous temp files
    for f in [temp_video_output, temp_audio_output, output_video]:
        if os.path.exists(f):
            os.remove(f)

    # Step 1: Detect scenes
    if progress_callback:
        progress_callback(1, 0, "Detecting scenes...")

    scenes, fps = detect_scenes(input_video)

    if not scenes:
        raise ValueError("No scenes detected in video")

    if progress_callback:
        progress_callback(1, 100, f"Found {len(scenes)} scenes")

    # Step 2: Analyze scenes
    if progress_callback:
        progress_callback(2, 0, "Analyzing scene content...")

    original_width, original_height = get_video_resolution(input_video)

    OUTPUT_HEIGHT = original_height
    OUTPUT_WIDTH = int(OUTPUT_HEIGHT * ASPECT_RATIO)
    if OUTPUT_WIDTH % 2 != 0:
        OUTPUT_WIDTH += 1

    scenes_analysis = []
    for i, (start_time_sc, end_time_sc) in enumerate(scenes):
        analysis = analyze_scene_content(input_video, start_time_sc, end_time_sc)
        strategy, target_box = decide_cropping_strategy(analysis, original_height)
        scenes_analysis.append({
            'start_frame': start_time_sc.get_frames(),
            'end_frame': end_time_sc.get_frames(),
            'analysis': analysis,
            'strategy': strategy,
            'target_box': target_box
        })
        if progress_callback:
            progress_callback(2, int((i + 1) / len(scenes) * 100), f"Analyzed {i + 1}/{len(scenes)} scenes")

    # Step 3: Process video frames
    if progress_callback:
        progress_callback(3, 0, "Processing video frames...")

    command = [
        'ffmpeg', '-y', '-f', 'rawvideo', '-vcodec', 'rawvideo',
        '-s', f'{OUTPUT_WIDTH}x{OUTPUT_HEIGHT}', '-pix_fmt', 'bgr24',
        '-r', str(fps), '-i', '-', '-c:v', 'libx264',
        '-preset', 'fast', '-crf', '23', '-an', temp_video_output
    ]

    ffmpeg_process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    cap = cv2.VideoCapture(input_video)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    frame_number = 0
    current_scene_index = 0

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        if current_scene_index < len(scenes_analysis) - 1 and \
           frame_number >= scenes_analysis[current_scene_index + 1]['start_frame']:
            current_scene_index += 1

        scene_data = scenes_analysis[current_scene_index]
        strategy = scene_data['strategy']
        target_box = scene_data['target_box']

        if strategy == 'TRACK':
            crop_box = calculate_crop_box(target_box, original_width, original_height)
            processed_frame = frame[crop_box[1]:crop_box[3], crop_box[0]:crop_box[2]]
            output_frame = cv2.resize(processed_frame, (OUTPUT_WIDTH, OUTPUT_HEIGHT))
        else:  # LETTERBOX
            # Create blurred background that fills the frame
            bg_scale = OUTPUT_HEIGHT / original_height
            bg_width = int(original_width * bg_scale)
            bg_frame = cv2.resize(frame, (bg_width, OUTPUT_HEIGHT))
            # Center crop to output width
            x_offset = (bg_width - OUTPUT_WIDTH) // 2
            bg_frame = bg_frame[:, x_offset:x_offset + OUTPUT_WIDTH]
            # Apply blur (downscale, blur, upscale for performance)
            small = cv2.resize(bg_frame, (OUTPUT_WIDTH // 4, OUTPUT_HEIGHT // 4))
            blurred_small = cv2.GaussianBlur(small, (25, 25), 0)
            blurred_bg = cv2.resize(blurred_small, (OUTPUT_WIDTH, OUTPUT_HEIGHT))

            # Scale the main content
            scale_factor = OUTPUT_WIDTH / original_width
            scaled_height = int(original_height * scale_factor)
            scaled_frame = cv2.resize(frame, (OUTPUT_WIDTH, scaled_height))

            # Composite: blurred background + sharp foreground
            output_frame = blurred_bg.copy()
            y_offset = (OUTPUT_HEIGHT - scaled_height) // 2
            output_frame[y_offset:y_offset + scaled_height, :] = scaled_frame

        ffmpeg_process.stdin.write(output_frame.tobytes())
        frame_number += 1

        if progress_callback and frame_number % 100 == 0:
            progress_callback(3, int(frame_number / total_frames * 100), f"Processed {frame_number}/{total_frames} frames")

    ffmpeg_process.stdin.close()
    stderr_output = ffmpeg_process.stderr.read().decode()
    ffmpeg_process.wait()
    cap.release()

    if ffmpeg_process.returncode != 0:
        raise RuntimeError(f"FFmpeg frame processing failed: {stderr_output}")

    # Step 4: Extract audio
    if progress_callback:
        progress_callback(4, 0, "Extracting audio...")

    audio_extract_command = [
        'ffmpeg', '-y', '-i', input_video, '-vn', '-acodec', 'copy', temp_audio_output
    ]
    result = subprocess.run(audio_extract_command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    if result.returncode != 0:
        raise RuntimeError(f"Audio extraction failed: {result.stderr.decode()}")

    if progress_callback:
        progress_callback(4, 100, "Audio extracted")

    # Step 5: Merge video and audio
    if progress_callback:
        progress_callback(5, 0, "Merging video and audio...")

    merge_command = [
        'ffmpeg', '-y', '-i', temp_video_output, '-i', temp_audio_output,
        '-c:v', 'copy', '-c:a', 'copy', output_video
    ]
    result = subprocess.run(merge_command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    if result.returncode != 0:
        raise RuntimeError(f"Final merge failed: {result.stderr.decode()}")

    if progress_callback:
        progress_callback(5, 100, "Complete")

    # Clean up temp files
    for f in [temp_video_output, temp_audio_output]:
        if os.path.exists(f):
            os.remove(f)

    end_time = time.time()

    return {
        'output_file': output_video,
        'scenes_detected': len(scenes),
        'total_frames': total_frames,
        'processing_time': end_time - start_time,
        'output_resolution': f"{OUTPUT_WIDTH}x{OUTPUT_HEIGHT}"
    }
