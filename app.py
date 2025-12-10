from flask import Flask, render_template, request, send_file, jsonify, after_this_request
import os
import yt_dlp
import re

app = Flask(__name__)

DOWNLOAD_FOLDER = 'downloads'
if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)


def sanitize_filename(filename):
    filename = re.sub(r'[\\/*?:"<>|]', "", filename)
    return filename[:200]


def format_filesize(bytes_size):
    if not bytes_size:
        return "Unknown"
    return f"{bytes_size / (1024*1024):.1f} MB"


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/get-info', methods=['POST'])
def get_info():
    try:
        data = request.get_json()
        url = data.get('url', '').strip()

        if not url:
            return jsonify({'error': 'URL tidak boleh kosong'}), 400

        if 'youtube.com' not in url and 'youtu.be' not in url:
            return jsonify({'error': 'URL harus dari YouTube'}), 400

        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'skip_download': True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        if not info:
            return jsonify({'error': 'Tidak dapat mengambil informasi video'}), 500

        formats = info.get('formats', [])

        video_streams = []
        seen_qualities = {}

        for f in formats:
            has_video = f.get('vcodec') and f.get('vcodec') != 'none'
            has_audio = f.get('acodec') and f.get('acodec') != 'none'

            if has_video and has_audio:
                height = f.get('height', 0)
                if height and height >= 144:
                    quality_key = f"{height}p"
                    if quality_key not in seen_qualities:
                        filesize = f.get('filesize') or f.get('filesize_approx', 0)
                        video_streams.append({
                            'format_id': f['format_id'],
                            'resolution': quality_key,
                            'filesize': format_filesize(filesize),
                            'ext': f.get('ext', 'mp4'),
                            'quality': height,
                            'type': 'video'
                        })
                        seen_qualities[quality_key] = True

        video_streams.sort(key=lambda x: x['quality'], reverse=True)

        audio_streams = []
        seen_audio = {}

        for f in formats:
            has_audio = f.get('acodec') and f.get('acodec') != 'none'
            no_video = not f.get('vcodec') or f.get('vcodec') == 'none'

            if has_audio and no_video:
                abr = f.get('abr', 0)
                if abr:
                    abr_key = int(abr)
                    if abr_key not in seen_audio and abr_key >= 32:
                        filesize = f.get('filesize') or f.get('filesize_approx', 0)
                        audio_streams.append({
                            'format_id': f['format_id'],
                            'abr': f"{abr_key}kbps",
                            'filesize': format_filesize(filesize),
                            'ext': f.get('ext', 'm4a'),
                            'quality': abr_key,
                            'type': 'audio'
                        })
                        seen_audio[abr_key] = True

        audio_streams.sort(key=lambda x: x['quality'], reverse=True)

        duration = info.get('duration', 0)
        duration_str = f"{duration // 60}:{duration % 60:02d}" if duration else "Unknown"

        return jsonify({
            'title': info.get('title', 'Unknown'),
            'thumbnail': info.get('thumbnail', ''),
            'duration': duration_str,
            'author': info.get('uploader', 'Unknown'),
            'views': info.get('view_count', 0),
            'video_streams': video_streams[:8],
            'audio_streams': audio_streams[:4]
        })

    except yt_dlp.utils.DownloadError as e:
        return jsonify({'error': f'Video tidak tersedia: {str(e)}'}), 400
    except Exception as e:
        return jsonify({'error': f'Error: {str(e)}'}), 500


@app.route('/download', methods=['POST'])
def download():
    try:
        data = request.get_json()
        url = data.get('url', '').strip()
        format_id = data.get('format_id')

        if not url or not format_id:
            return jsonify({'error': 'URL dan format_id diperlukan'}), 400

        ydl_opts = {
            'format': format_id,
            'outtmpl': os.path.join(DOWNLOAD_FOLDER, '%(title)s.%(ext)s'),
            'quiet': True,
            'no_warnings': True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)

        if not os.path.exists(filename):
            return jsonify({'error': 'File download gagal'}), 500

        @after_this_request
        def remove_file(response):
            try:
                os.remove(filename)
            except Exception as e:
                app.logger.error(f"Error removing file: {e}")
            return response

        return send_file(
            filename,
            as_attachment=True,
            download_name=os.path.basename(filename),
            mimetype='application/octet-stream'
        )

    except yt_dlp.utils.DownloadError as e:
        return jsonify({'error': f'Download gagal: {str(e)}'}), 400
    except Exception as e:
        return jsonify({'error': f'Error: {str(e)}'}), 500


@app.route('/health')
def health():
    return jsonify({'status': 'ok'}), 200


def cleanup_downloads():
    try:
        for filename in os.listdir(DOWNLOAD_FOLDER):
            file_path = os.path.join(DOWNLOAD_FOLDER, filename)
            if os.path.isfile(file_path):
                os.remove(file_path)
    except Exception as e:
        print(f"Cleanup error: {e}")


if __name__ == '__main__':
    cleanup_downloads()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
