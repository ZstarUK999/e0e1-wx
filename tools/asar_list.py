import json, os, struct, sys

def read_header(p):
    with open(p, 'rb') as f:
        # uint32 magic/version, uint32 header size(payload?), ...
        # asar: [4]uint32 = 4, then header size pickle
        b = f.read(16)
        # standard: uint32 =4; uint32 = header_string_size? Actually:
        # struct: uint32 (4), uint32 (header size), uint32 (header string size), uint32 (?)
        v = struct.unpack('<IIII', b)
    return v

def load(p):
    with open(p, 'rb') as f:
        raw = f.read(16)
        _, _, _, hdr_size = struct.unpack('<IIII', raw)
        s = f.read(hdr_size)
    return json.loads(s.decode('utf-8'))

def walk(node, prefix=''):
    for name, ent in (node.get('files') or {}).items():
        p = prefix + '/' + name
        if ent.get('files'):
            print(f"D {p}")
            walk(ent, p)
        else:
            print(f"F {p}\t{ent.get('size', 0)}\t{ent.get('offset', '')}")

if __name__ == '__main__':
    h = load(sys.argv[1])
    walk(h)
