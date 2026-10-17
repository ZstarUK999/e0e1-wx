import sys
import uiautomation as auto

def dump(c, depth=0, maxdepth=6, out=None, limit=600):
    if depth > maxdepth or out[0] >= limit:
        return
    try:
        name = (c.Name or '').replace('\n', ' ')[:70]
        ct = c.ControlTypeName
        out[0] += 1
        print('  ' * depth + f'[{ct}] "{name}" cls={c.ClassName} id={c.AutomationId}')
    except Exception:
        return
    try:
        for ch in c.GetChildren():
            dump(ch, depth + 1, maxdepth, out, limit)
    except Exception:
        pass

if __name__ == '__main__':
    pid = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    md = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    for w in auto.GetRootControl().GetChildren():
        try:
            if pid and w.ProcessId != pid:
                continue
            if not pid and not (('douyin' in str(w.Name).lower()) or ('抖音' in str(w.Name))):
                continue
        except Exception:
            continue
        print('=== WINDOW', w.Name, w.ClassName, 'pid', w.ProcessId)
        out = [0]
        dump(w, 0, md, out)
        print()
