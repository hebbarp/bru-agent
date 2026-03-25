"""
Media Tools Skills - ImageMagick and FFmpeg for image/audio/video processing.
"""

import asyncio
import shutil
from pathlib import Path
from typing import Any, Dict
from loguru import logger

from ..base import BaseSkill


class ImageMagickSkill(BaseSkill):
    """Skill for image processing using ImageMagick."""

    name = "process_image"
    description = """Process or convert images using ImageMagick. Capabilities include:
- Convert between formats (PNG, JPG, GIF, WebP, PDF, etc.)
- Resize images
- Crop, rotate, flip images
- Add text/watermarks
- Adjust colors, brightness, contrast
- Create thumbnails
- Combine/composite images

Use this when asked to edit, convert, resize, or process images."""
    version = "1.0.0"

    def __init__(self, config: dict = None):
        super().__init__(config)
        self.output_dir = Path(config.get('output_dir', './output')) if config else Path('./output')
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "input_path": {
                    "type": "string",
                    "description": "Path to input image file"
                },
                "output_filename": {
                    "type": "string",
                    "description": "Output filename with extension (e.g., 'output.png', 'resized.jpg')"
                },
                "operations": {
                    "type": "string",
                    "description": "ImageMagick operations (e.g., '-resize 50%', '-rotate 90', '-crop 100x100+10+10')"
                },
                "input_content_base64": {
                    "type": "string",
                    "description": "Optional: Base64 encoded image content if no input_path"
                }
            },
            "required": ["output_filename"]
        }

    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Process image using ImageMagick."""
        input_path = params.get('input_path', '')
        output_filename = params.get('output_filename', '')
        operations = params.get('operations', '')

        if not output_filename:
            return {"success": False, "error": "No output filename specified"}

        # Check if ImageMagick is installed
        magick_cmd = 'magick' if shutil.which('magick') else 'convert'
        if not shutil.which(magick_cmd):
            return {
                "success": False,
                "error": "ImageMagick is not installed. Please install it from https://imagemagick.org/"
            }

        output_path = self.output_dir / output_filename

        try:
            # Build command
            cmd = [magick_cmd]

            if input_path:
                input_file = Path(input_path)
                if not input_file.exists():
                    return {"success": False, "error": f"Input file not found: {input_path}"}
                cmd.append(str(input_file))

            if operations:
                cmd.extend(operations.split())

            cmd.append(str(output_path))

            logger.info(f"Running ImageMagick: {' '.join(cmd)}")

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=120
                )
            except asyncio.TimeoutError:
                process.kill()
                return {"success": False, "error": "ImageMagick processing timed out"}

            if process.returncode != 0:
                error_msg = stderr.decode('utf-8', errors='replace') if stderr else "Unknown error"
                return {"success": False, "error": f"ImageMagick failed: {error_msg}"}

            if output_path.exists():
                return {
                    "success": True,
                    "result": {
                        "message": f"Image processed successfully",
                        "output_path": str(output_path),
                        "filename": output_filename,
                        "size_bytes": output_path.stat().st_size
                    }
                }
            else:
                return {"success": False, "error": "Output file was not created"}

        except Exception as e:
            logger.error(f"ImageMagick processing failed: {e}")
            return {"success": False, "error": f"ImageMagick processing failed: {str(e)}"}


class FFmpegSkill(BaseSkill):
    """Skill for audio/video processing using FFmpeg."""

    name = "process_media"
    description = """Process audio and video files using FFmpeg. Capabilities include:
- Convert between formats (MP4, AVI, MKV, MP3, WAV, etc.)
- Extract audio from video
- Trim/cut clips
- Resize/scale video
- Adjust volume, add audio effects
- Create thumbnails from video
- Combine audio and video
- Add subtitles

Use this when asked to convert, edit, or process audio/video files."""
    version = "1.0.0"

    def __init__(self, config: dict = None):
        super().__init__(config)
        self.output_dir = Path(config.get('output_dir', './output')) if config else Path('./output')
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "input_path": {
                    "type": "string",
                    "description": "Path to input media file"
                },
                "output_filename": {
                    "type": "string",
                    "description": "Output filename with extension (e.g., 'output.mp3', 'converted.mp4')"
                },
                "options": {
                    "type": "string",
                    "description": "FFmpeg options (e.g., '-ss 00:01:00 -t 30' to extract 30 seconds starting at 1 minute, '-vn' for audio only)"
                },
                "preset": {
                    "type": "string",
                    "description": "Optional preset: 'audio_only' (extract audio), 'compress' (reduce file size), 'thumbnail' (extract frame)"
                }
            },
            "required": ["input_path", "output_filename"]
        }

    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Process media using FFmpeg."""
        input_path = params.get('input_path', '')
        output_filename = params.get('output_filename', '')
        options = params.get('options', '')
        preset = params.get('preset', '')

        if not input_path:
            return {"success": False, "error": "No input path specified"}

        if not output_filename:
            return {"success": False, "error": "No output filename specified"}

        # Check if FFmpeg is installed
        if not shutil.which('ffmpeg'):
            return {
                "success": False,
                "error": "FFmpeg is not installed. Please install it from https://ffmpeg.org/"
            }

        input_file = Path(input_path)
        if not input_file.exists():
            return {"success": False, "error": f"Input file not found: {input_path}"}

        output_path = self.output_dir / output_filename

        try:
            # Build command based on preset or custom options
            cmd = ['ffmpeg', '-i', str(input_file), '-y']  # -y to overwrite

            if preset == 'audio_only':
                cmd.extend(['-vn', '-acodec', 'libmp3lame', '-q:a', '2'])
            elif preset == 'compress':
                cmd.extend(['-vcodec', 'libx264', '-crf', '28', '-preset', 'medium'])
            elif preset == 'thumbnail':
                cmd.extend(['-ss', '00:00:01', '-vframes', '1'])
            elif options:
                cmd.extend(options.split())

            cmd.append(str(output_path))

            logger.info(f"Running FFmpeg: {' '.join(cmd)}")

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=600  # 10 minutes for video processing
                )
            except asyncio.TimeoutError:
                process.kill()
                return {"success": False, "error": "FFmpeg processing timed out"}

            if process.returncode != 0:
                error_msg = stderr.decode('utf-8', errors='replace')[-1000:] if stderr else "Unknown error"
                return {"success": False, "error": f"FFmpeg failed: {error_msg}"}

            if output_path.exists():
                return {
                    "success": True,
                    "result": {
                        "message": f"Media processed successfully",
                        "output_path": str(output_path),
                        "filename": output_filename,
                        "size_bytes": output_path.stat().st_size
                    }
                }
            else:
                return {"success": False, "error": "Output file was not created"}

        except Exception as e:
            logger.error(f"FFmpeg processing failed: {e}")
            return {"success": False, "error": f"FFmpeg processing failed: {str(e)}"}


class FFprobeSkill(BaseSkill):
    """Skill for getting media file information using FFprobe."""

    name = "get_media_info"
    description = """Get detailed information about audio/video files using FFprobe. Returns:
- Duration, format, bitrate
- Video: resolution, codec, frame rate
- Audio: sample rate, channels, codec
- Metadata: title, artist, etc.

Use this when asked to analyze or get information about media files."""
    version = "1.0.0"

    def __init__(self, config: dict = None):
        super().__init__(config)

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "input_path": {
                    "type": "string",
                    "description": "Path to media file to analyze"
                }
            },
            "required": ["input_path"]
        }

    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get media information using FFprobe."""
        input_path = params.get('input_path', '')

        if not input_path:
            return {"success": False, "error": "No input path specified"}

        # Check if FFprobe is installed
        if not shutil.which('ffprobe'):
            return {
                "success": False,
                "error": "FFprobe is not installed. Please install FFmpeg from https://ffmpeg.org/"
            }

        input_file = Path(input_path)
        if not input_file.exists():
            return {"success": False, "error": f"Input file not found: {input_path}"}

        try:
            cmd = [
                'ffprobe',
                '-v', 'quiet',
                '-print_format', 'json',
                '-show_format',
                '-show_streams',
                str(input_file)
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=30
                )
            except asyncio.TimeoutError:
                process.kill()
                return {"success": False, "error": "FFprobe timed out"}

            if process.returncode != 0:
                error_msg = stderr.decode('utf-8', errors='replace') if stderr else "Unknown error"
                return {"success": False, "error": f"FFprobe failed: {error_msg}"}

            import json
            info = json.loads(stdout.decode('utf-8'))

            return {
                "success": True,
                "result": {
                    "message": "Media information retrieved",
                    "info": info
                }
            }

        except Exception as e:
            logger.error(f"FFprobe failed: {e}")
            return {"success": False, "error": f"FFprobe failed: {str(e)}"}
