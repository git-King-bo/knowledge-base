"""Isolated parser: parent imposes a wall-clock deadline; never calls external models."""
import json
from pathlib import Path
import sys
import zipfile
from app.services.ingestion import parse_uploaded_file
from app.services.talent_import import read_personnel


def parse(path, filename, source_id):
    data = path.read_bytes()
    if len(data)>20*1024*1024:
        raise ValueError('文件超过20MB')
    if filename.lower().endswith(('.xlsx','.docx')):
        with zipfile.ZipFile(path) as archive:
            entries=archive.infolist()
            if len(entries)>10000 or sum(x.file_size for x in entries)>100*1024*1024:
                raise ValueError('文档解压后过大')
    parsed=parse_uploaded_file(filename,data)
    if not parsed.text.strip():
        from app.core.config import settings
        if settings.ocr_enabled and filename.lower().endswith('.pdf'):
            import subprocess,tempfile
            with tempfile.TemporaryDirectory() as folder:
                out=Path(folder)/'ocr.pdf'
                subprocess.run(['ocrmypdf','--skip-text','--pages','1-50','--tesseract-timeout','20',str(path),str(out)],
                               check=True,timeout=180,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                parsed=parse_uploaded_file(filename,out.read_bytes())
        if not parsed.text.strip():
            raise ValueError('没有可解析文本，扫描件需要启用OCR')
    if len(parsed.text)>5_000_000:
        raise ValueError('解析文本超过500万字符')
    return {'text':parsed.text,'mime_type':parsed.mime_type,'title':parsed.title,
            'talents':read_personnel(path,source_id) if filename.lower().endswith('.xlsx') else []}

if __name__=='__main__':
    if sys.platform == 'linux':
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (1500 * 1024 * 1024, 1500 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CPU, (180, 180))
    try:
        print(json.dumps(parse(Path(sys.argv[1]),sys.argv[2],sys.argv[3]),ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({'error':str(exc)},ensure_ascii=False))
        sys.exit(1)
