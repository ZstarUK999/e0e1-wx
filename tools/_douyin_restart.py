"""Restart Douyin PC and wait for the mini-game file-server (127.0.0.1:5678) to come up."""
import subprocess, time, socket, sys

EXE = r'C:\Program Files (x86)\ByteDance\douyin\douyin.exe'
PORT = 5678


def kill():
    subprocess.run(['taskkill', '/IM', 'douyin.exe', '/F'],
                   capture_output=True, text=True)
    time.sleep(4)


def up(port=PORT, host='127.0.0.1'):
    s = socket.socket()
    s.settimeout(1.5)
    try:
        s.connect((host, port))
        return True
    except Exception:
        return False
    finally:
        s.close()


def main():
    secs = int(sys.argv[1]) if len(sys.argv) > 1 else 90
    kill()
    subprocess.Popen([EXE], cwd=r'C:\Program Files (x86)\ByteDance\douyin',
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print('launched, waiting for :%d ...' % PORT)
    for i in range(secs // 3):
        time.sleep(3)
        if up():
            print('game file-server UP after ~%ds' % (i * 3))
            return 0
    print('file-server did NOT come up within %ds (session restore off?)' % secs)
    return 1


if __name__ == '__main__':
    sys.exit(main())
