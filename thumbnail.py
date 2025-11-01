# Script to process videos from 'old Coding/done', add neon text to first 0.5 seconds, and save to 'Old Coding2'
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import os
import random
import subprocess

OLD_DIR = 'file path here'
NEW_DIR = 'output file ppath here'
FONT_SIZE = 110

# 6 different neon colors
NEON_COLORS = [
    (0, 255, 255),   # Cyan
    (255, 0, 255),   # Magenta
    (255, 255, 0),   # Yellow
    (0, 255, 0),     # Green
    (255, 0, 0),     # Red
    (255, 165, 0),   # Orange
]

# Try to load Impact font for more neon-like appearance, fallback to Arial, then default
try:
    FONT_PATH = '/Library/Fonts/Impact.ttf'
    font = ImageFont.truetype(FONT_PATH, FONT_SIZE)
except:
    try:
        FONT_PATH = '/Library/Fonts/Arial.ttf'
        font = ImageFont.truetype(FONT_PATH, FONT_SIZE)
    except:
        FONT_PATH = None
        font = ImageFont.load_default()

def has_audio(filepath):
    try:
        result = subprocess.run(['ffprobe', '-i', filepath, '-show_streams', '-select_streams', 'a', '-loglevel', 'error'], capture_output=True, text=True)
        return result.returncode == 0 and 'codec_type=audio' in result.stdout
    except:
        return False

def add_neon_text(frame, text, font, color):
    # Convert frame to PIL Image
    img_pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(img_pil)
    
    # Text wrapping
    max_width = img_pil.width - 100  # margin
    words = text.split()
    lines = []
    current_line = ""
    for word in words:
        test_line = current_line + " " + word if current_line else word
        bbox = draw.textbbox((0, 0), test_line, font=font)
        w_test = bbox[2] - bbox[0]
        if w_test > max_width:
            if current_line:
                lines.append(current_line)
                current_line = word
            else:
                lines.append(word)  # force long word
        else:
            current_line = test_line
    if current_line:
        lines.append(current_line)
    
    # Angle for text
    angle = 5  # slight right tilt upward
    
    # Process each line
    text_images = []
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        # Create text image with transparency
        text_img = Image.new('RGBA', (w + 40, h + 40), (0, 0, 0, 0))
        draw_text = ImageDraw.Draw(text_img)
        
        # Draw thicker white outline around text
        outline_offsets = []
        for dx in range(-5, 6):
            for dy in range(-5, 6):
                if abs(dx) + abs(dy) <= 5:  # Diamond shape to avoid too many pixels
                    outline_offsets.append((dx, dy))
        for dx, dy in outline_offsets:
            draw_text.text((20 + dx, 20 + dy), line, font=font, fill=(255, 255, 255, 255))
        
        # Glow colors
        glow_offsets = [8, 4, 0]
        glow_colors = [
            tuple(min(255, c + 50) for c in color) + (255,),
            tuple(max(0, c - 50) for c in color) + (255,),
            color + (255,)
        ]
        
        # Draw glows
        for offset, glow_color in zip(glow_offsets, glow_colors):
            draw_text.text((20 - offset, 20 - offset), line, font=font, fill=glow_color)
            draw_text.text((20 + offset, 20 + offset), line, font=font, fill=glow_color)
        
        # Draw thin black outline around the main text
        black_outline_offsets = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
        for dx, dy in black_outline_offsets:
            draw_text.text((20 + dx, 20 + dy), line, font=font, fill=(0, 0, 0, 255))
        
        draw_text.text((20, 20), line, font=font, fill=color + (255,))
        
        # Rotate
        rotated = text_img.rotate(angle, expand=True)
        text_images.append(rotated)
    
    # Position lines
    total_height = sum(img.height for img in text_images) + (len(text_images) - 1) * 5
    y_start = max(50, (img_pil.height - total_height) // 5)  # Ensure minimum margin from top
    x_center = img_pil.width // 2
    
    # Draw semi-transparent black background behind all text
    bg_width = max(img.width for img in text_images) + 40  # Extra padding
    bg_height = total_height + 20
    bg_x = x_center - bg_width // 2
    bg_y = y_start - 10
    # Create background rectangle with transparency
    bg_overlay = Image.new('RGBA', (bg_width, bg_height), (0, 0, 0, 120))  # Semi-transparent black
    img_pil.paste(bg_overlay, (bg_x, bg_y), bg_overlay)
    
    current_y = y_start
    for rotated in text_images:
        x = x_center - rotated.width // 2
        img_pil.paste(rotated, (x, current_y), rotated)
        current_y += rotated.height + 5
    
    # Convert back to OpenCV frame
    return cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)

def process_video(input_path, output_path, title_text):
    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        print(f"Error opening video: {input_path}")
        return
    
    # Select a random neon color for this video
    random_color = random.choice(NEON_COLORS)
    
    fps = cap.get(cv2.CAP_PROP_FPS)
    frames_to_modify = int(0.5 * fps)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))

    frame_count = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if frame_count < frames_to_modify:
            frame = add_neon_text(frame, title_text, font, random_color)
        out.write(frame)
        frame_count += 1

    cap.release()
    out.release()
    
    # Preserve audio by muxing with original if it has audio
    if has_audio(input_path):
        try:
            temp_output = output_path + '.temp.mp4'
            result = subprocess.run(['ffmpeg', '-i', output_path, '-i', input_path, '-c', 'copy', '-map', '0:v', '-map', '1:a', '-y', temp_output], check=True, capture_output=True, text=True)
            os.replace(temp_output, output_path)
            print(f"Audio preserved for: {os.path.basename(output_path)}")
        except subprocess.CalledProcessError as e:
            print(f"Warning: Could not preserve audio for {os.path.basename(output_path)}")
            print(f"ffmpeg stderr: {e.stderr}")
            if os.path.exists(temp_output):
                os.remove(temp_output)
    else:
        print(f"No audio to preserve for: {os.path.basename(output_path)}")
    
    print(f"Processed: {os.path.basename(input_path)} -> {os.path.basename(output_path)} (Title: '{title_text}', Color: {random_color})")

def main():
    if not os.path.exists(OLD_DIR):
        print(f"Source directory does not exist: {OLD_DIR}")
        return
    if not os.path.exists(NEW_DIR):
        os.makedirs(NEW_DIR)
    
    for filename in os.listdir(OLD_DIR):
        if filename.lower().endswith('.mp4'):
            title = os.path.splitext(filename)[0]
            input_path = os.path.join(OLD_DIR, filename)
            output_path = os.path.join(NEW_DIR, filename)
            process_video(input_path, output_path, title)

if __name__ == "__main__":
    main()
