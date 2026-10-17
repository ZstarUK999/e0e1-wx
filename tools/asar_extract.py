import json, os, struct, sys

def load(p):
    with open(p, 'rb') as f:
        struct.unpack('<IIII', f.read(16))
        # reopen properly
    with open(p, 'rb') as f:
        raw = f.read(16)
        _, _, _, hdr_size = struct.unpack('<IIII', raw)
        s = f.read(hdr_size)
    return json.loads(s.decode('utf-8')), 16 + hdr_size

def extract(entries, base, out, f):
    for name, ent in entries.items():
        p = os.path.join(out, name)
        if ent.get('files'):
            os.makedirs(p, exist_ok=True)
            extract(ent['files'], base, p, f)
        elif 'link' in ent:
            continue
        else:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            if 'offset' not in ent:
                continue
            off = base + int(ent['offset'])
            f.seek(off)
            with open(p, 'wb') as o:
                o.write(f.read(ent['size']))

if __name__ == '__main__':
    src, out = sys.argv[1], sys.argv[2]
    hdr, base = load(src)
    os.makedirs(out, exist_ok=True)
    with open(src, 'rb') as f:
        extract(hdr['files'], base, out, f)
    print('done ->', out)
