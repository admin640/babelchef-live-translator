const fs = require('fs');
global.window = global;
global.navigator = { userAgent: 'node' };
eval(fs.readFileSync('livekit-client.umd.min.js', 'utf8'));
console.log(Object.keys(window.LivekitClient));
