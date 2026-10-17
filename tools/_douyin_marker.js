// probe: writes a marker when loaded by douyin main process
try {
  const fs = require('fs');
  fs.writeFileSync('C:/Users/AshenZhou/AppData/Local/Temp/douyin_marker.txt',
    'loaded pid=' + process.pid + ' type=' + (process.type || 'node') + ' argv=' + JSON.stringify(process.argv) + '\n');
} catch (e) {}
