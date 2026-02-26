import os
import threading
import tempfile
from flask import Flask, render_template, request, jsonify, send_from_directory
import yt_dlp

app = Flask(__name__)

download_status = {}

def get_status_hook(video_id):
    def hook(d):
        if d['status'] == 'downloading':
            pct = d.get('_percent_str', '...').strip()
            download_status[video_id] = {'state': 'downloading', 'progress': pct}
        elif d['status'] == 'finished':
            download_status[video_id] = {'state': 'converting'}
    return hook

def do_download(url, video_id, tmp_dir):
    opts = {
        'format': 'bestaudio/best',
        'outtmpl': f'{tmp_dir}/%(title)s.%(ext)s',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'progress_hooks': [get_status_hook(video_id)],
        'noplaylist': True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info).rsplit('.', 1)[0] + '.mp3'
        filename = os.path.basename(filename)
    download_status[video_id] = {'state': 'done', 'filename': filename, 'tmp_dir': tmp_dir}

@app.route('/')
def index():
    return render_template('index.html')

def format_duration(seconds):
    if not seconds:
        return ''
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h:
        return f"{h}:{m:02}:{s:02}"
    return f"{m}:{s:02}"

@app.route('/search')
def search():
    query = request.args.get('q', '')
    if not query:
        return jsonify([])
    opts = {
        'quiet': True,
        'extract_flat': True,
        'skip_download': True,
        'no_warnings': True,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            results = ydl.extract_info(f"ytsearch10:{query}", download=False)
        entries = results.get('entries', [])
        return jsonify([{
            'id': e['id'],
            'title': e['title'],
            'duration': format_duration(e.get('duration')),
            'thumbnail': f"https://i.ytimg.com/vi/{e['id']}/mqdefault.jpg",
            'url': f"https://www.youtube.com/watch?v={e['id']}",
            'views': e.get('view_count'),
            'channel': e.get('channel', e.get('uploader', '')),
            'album': e.get('album', ''),
        } for e in entries if e])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/download', methods=['POST'])
def download():
    data = request.json
    video_id = data['id']
    url = data['url']
    if video_id in download_status and download_status[video_id]['state'] != 'done':
        return jsonify({'message': 'Already downloading'})
    tmp_dir = tempfile.mkdtemp()  # unique temp folder per download
    download_status[video_id] = {'state': 'queued'}
    threading.Thread(target=do_download, args=(url, video_id, tmp_dir), daemon=True).start()
    return jsonify({'message': 'Started'})

@app.route('/status/<video_id>')
def status(video_id):
    return jsonify(download_status.get(video_id, {'state': 'unknown'}))

@app.route('/files/<video_id>')
def serve_file(video_id):
    info = download_status.get(video_id)
    if not info or info['state'] != 'done':
        return 'Not ready', 404
    tmp_dir = info['tmp_dir']
    filename = info['filename']

    def cleanup():
        filepath = os.path.join(tmp_dir, filename)
        if os.path.exists(filepath):
            os.remove(filepath)
        if os.path.exists(tmp_dir):
            os.rmdir(tmp_dir)
        download_status.pop(video_id, None)

    response = send_from_directory(tmp_dir, filename, as_attachment=True)
    threading.Thread(target=cleanup, daemon=True).start()
    return response

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 7860))
    app.run(host='0.0.0.0', port=port)