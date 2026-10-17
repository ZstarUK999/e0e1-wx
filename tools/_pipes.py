import os
try:
    ps = os.listdir(r'\\.\pipe\\')
except Exception as e:
    print('err', e)
    ps = []
print('total', len(ps))
for p in ps:
    lp = p.lower()
    if any(k in lp for k in ('chrom', 'devtool', 'electron', 'douyin', 'lynx', 'byte')):
        print(p)
