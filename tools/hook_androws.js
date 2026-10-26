// 应用宝 2.4.4.20121：独立配置，不使用微信新版的 RemoteDebugMode 字段。
'use strict';
const DEBUG_PORT = 9422;
const config = JSON.parse(`@@CONFIG@@`);
let installed = false;
let loadHook = null;
let filterCallback = null;
function stringValue(p) {
    const size = p.add(23).readS8();
    if (size >= 0) {
        if (size > 23) throw new Error('invalid short string');
        return p.readUtf8String(size);
    }
    const length = p.add(8).readU32();
    if (length > 4096) throw new Error('invalid string length');
    return p.readPointer().readUtf8String(length);
}
function checkBytes(address, expected) {
    const bytes = new Uint8Array(address.readByteArray(expected.length / 2));
    const actual = Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('');
    if (actual !== expected) throw new Error('应用宝函数指纹不匹配，停止 Hook');
}
rpc.exports = {
    install() {
        if (installed) return true;
        const module = Process.getModuleByName('flue.dll');
        if (!module.path.replace(/\//g, '\\').toLowerCase().includes('\\androws\\wmpfruntime\\')) {
            throw new Error('目标不是应用宝运行库');
        }
        const load = module.base.add(config.LoadStartHookOffset);
        const filter = module.base.add(config.CDPFilterHookOffset);
        const cast = module.base.add(config.CastToJsonHookOffset);
        checkBytes(load, '415741565657534881ec9001000089d3');
        checkBytes(filter, '4157415641554154565755534881ecb8');
        checkBytes(cast, '5657534881ec900100004889ce488b05');
        const convert = new NativeFunction(cast, 'pointer', ['pointer', 'pointer']);
        filterCallback = new NativeCallback((self, output, input) => {
            convert(output, input);
            return output;
        }, 'pointer', ['pointer', 'pointer', 'pointer']);
        loadHook = Interceptor.attach(load, {onEnter(args) {
            try {
                const root = args[0].add(64).readPointer();
                if (stringValue(root.add(152)) !== config.TargetAppId) return;
                const layout = config.MiniAppConfigStructOffsets;
                let launch = args[0];
                for (const offset of layout.LaunchConfigOffsets) launch = launch.add(offset).readPointer();
                let remote = launch;
                for (const offset of layout.RemoteDebugConfigOffsets) remote = remote.add(offset).readPointer();
                const scene = remote.add(layout.SceneOffset);
                const urlPtr = launch.add(layout.WebSocketURLStringOffset);
                const oldUrl = stringValue(urlPtr);
                const oldScene = scene.readInt();
                const url = `ws://127.0.0.1:${DEBUG_PORT}`;
                // URL fits libc++'s 23-byte SSO. Reuse a long buffer only if its
                // capacity (long representation implies >=24) can hold this URL.
                if (url.length > 23) throw new Error('调试地址过长');
                if (urlPtr.add(23).readS8() < 0) {
                    urlPtr.readPointer().writeUtf8String(url);
                    urlPtr.add(8).writeU64(url.length);
                } else {
                    urlPtr.writeUtf8String(url);
                    urlPtr.add(23).writeU8(url.length);
                }
                scene.writeInt(1101);
                args[1] = ptr(1);
                send({type:'androws-load', appid:config.TargetAppId, previousScene:oldScene, hadUrl:!!oldUrl});
            } catch (error) {
                send({type:'androws-hook-error', error:String(error)});
            }
        }});
        try {
            Interceptor.replace(filter, filterCallback);
            Interceptor.flush();
            installed = true;
            return true;
        } catch (error) {
            loadHook.detach();
            throw error;
        }
    }
};
