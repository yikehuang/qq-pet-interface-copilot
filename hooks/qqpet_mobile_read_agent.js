'use strict';

// QQ Pet mobile bridge. Reads use a strict allow-list. The sole write entry is
// exposed through a separate one-shot RPC so callers cannot accidentally retry
// an uncertain state-changing request.
const ALLOWED_READS = {
  'OidbSvcTrpcTcp.0x95e1_0': '38369:0',
  'OidbSvcTrpcTcp.0x96f2_1': '38642:1',
  'OidbSvcTrpcTcp.0x9949_1': '39241:1',
  'OidbSvcTrpcTcp.0x9bf1_1': '39921:1',
  'OidbSvcTrpcTcp.0x9bf2_1': '39922:1',
  'OidbSvcTrpcTcp.0x9b60_1': '39776:1',
  'OidbSvcTrpcTcp.0x9ab2_1': '39602:1',
  'OidbSvcTrpcTcp.0x975a_1': '38746:1',
  'OidbSvcTrpcTcp.0x99f2_1': '39410:1',
  'OidbSvcTrpcTcp.0x96a4_1': '38564:1',
  'OidbSvcTrpcTcp.0x976c_0': '38764:0',
  'OidbSvcTrpcTcp.0x9ad4_1': '39636:1',
  'OidbSvcTrpcTcp.0x985d_0': '39005:0',
  'OidbSvcTrpcTcp.0x975f_1': '38751:1',
};
const ALLOWED_ONE_SHOT_WRITES = {
  'OidbSvcTrpcTcp.0x975e_1': '38750:1',
  'OidbSvcTrpcTcp.0x992d_1': '39213:1',
  'OidbSvcTrpcTcp.0x99df_1': '39391:1',
  'OidbSvcTrpcTcp.0x9bf3_1': '39923:1',
  'OidbSvcTrpcTcp.0x9bd0_0': '39888:0',
  'OidbSvcTrpcTcp.0x96a6_1': '38566:1',
  'OidbSvcTrpcTcp.0x985b_0': '39003:0',
  'OidbSvcTrpcTcp.0x9760_1': '38752:1',
  'OidbSvcTrpcTcp.0x9c44_1': '40004:1',
};

function hexToBytes(hex) {
  if (typeof hex !== 'string' || (hex.length % 2) !== 0) {
    throw new Error('invalid hex body');
  }
  const values = [];
  for (let i = 0; i < hex.length; i += 2) {
    const value = parseInt(hex.slice(i, i + 2), 16);
    values.push(value > 127 ? value - 256 : value);
  }
  return Java.array('byte', values);
}

function bytesToHex(value) {
  if (value === null || value === undefined) return '';
  const bytes = Java.array('byte', value);
  let out = '';
  for (let i = 0; i < bytes.length; i++) {
    out += ('0' + (bytes[i] & 0xff).toString(16)).slice(-2);
  }
  return out;
}

function sendOidbPacket(commandName, command, subCommand, bodyHex) {
  return new Promise((resolve, reject) => {
    Java.perform(() => {
      let settled = false;
      const finish = (result, error) => {
        if (settled) return;
        settled = true;
        if (error) reject(error);
        else resolve(result);
      };

      try {
        const Delegate = Java.use('com.tencent.mobileqq.qqpet.delegate.l');
        const CallbackInterface = Java.use(
          'com.tencent.ergo.hostdelegate.pb.PetPbDelegate$a'
        );
        const callbackName =
          'com.tencent.mobileqq.qqpet.CodexPacketCallback' + Date.now() +
          Math.floor(Math.random() * 1000000);
        const Callback = Java.registerClass({
          name: callbackName,
          implements: [CallbackInterface],
          methods: {
            onResult(code, data, bundle) {
              let message = '';
              try {
                if (bundle) message = String(bundle.getString('data_error_msg') || '');
              } catch (_) {}
              finish({
                code: Number(code),
                data_hex: bytesToHex(data),
                message: message,
              });
            },
          },
        });
        const delegate = Delegate.$new();
        delegate.c(
          hexToBytes(String(bodyHex || '')),
          String(commandName),
          Number(command),
          Number(subCommand),
          Callback.$new()
        );
        setTimeout(() => finish(null, new Error('mobile QQ packet timed out')), 12000);
      } catch (error) {
        finish(null, error);
      }
    });
  });
}

rpc.exports = {
  ping() {
    return { ok: true, process: 'com.tencent.mobileqq' };
  },

  javaReady() {
    return typeof Java !== 'undefined' && Java.available === true;
  },

  getSelfUin() {
    return new Promise((resolve, reject) => {
      Java.perform(() => {
        try {
          const MobileQQ = Java.use('mqq.app.MobileQQ');
          const runtime = MobileQQ.sMobileQQ.value.peekAppRuntime();
          if (!runtime) throw new Error('QQ runtime is unavailable');
          resolve(String(runtime.getCurrentAccountUin()));
        } catch (error) {
          reject(error);
        }
      });
    });
  },

  getLoginState() {
    return new Promise((resolve, reject) => {
      Java.perform(() => {
        try {
          const MobileQQ = Java.use('mqq.app.MobileQQ');
          const runtime = MobileQQ.sMobileQQ.value.peekAppRuntime();
          if (!runtime) throw new Error('QQ runtime is unavailable');
          const uin = String(runtime.getCurrentAccountUin() || '');
          let loggedIn = /^\d+$/.test(uin) && uin !== '0';
          let source = 'account_uin';
          try {
            loggedIn = Boolean(runtime.isLogin());
            source = 'runtime.isLogin';
          } catch (_) {
            // Older QQ builds may not expose AppRuntime.isLogin().
          }
          resolve({ uin: uin, logged_in: loggedIn, source: source });
        } catch (error) {
          reject(error);
        }
      });
    });
  },

  sendOidbRead(commandName, command, subCommand, bodyHex) {
    const expected = ALLOWED_READS[String(commandName)];
    if (expected !== String(command) + ':' + String(subCommand)) {
      throw new Error('command is not in the read-only allow-list');
    }

    return sendOidbPacket(commandName, command, subCommand, bodyHex);
  },

  sendOidbWriteOnce(commandName, command, subCommand, bodyHex) {
    const expected = ALLOWED_ONE_SHOT_WRITES[String(commandName)];
    if (expected !== String(command) + ':' + String(subCommand)) {
      throw new Error('command is not in the one-shot write allow-list');
    }
    return sendOidbPacket(commandName, command, subCommand, bodyHex);
  },

  // 打开 QQ 宠物主页（PetMainFragment）供用户查看。与 OIDB 读写共用同一个
  // frida script / Java bridge（不新建第二个 session，避免两个 frida-agent
  // 的 JNI hook 在同一个 QQ 进程内冲突导致崩溃）。
  openPetPage() {
    return new Promise((resolve, reject) => {
      Java.perform(() => {
        try {
          const Intent = Java.use('android.content.Intent');
          const Unit = Java.use('kotlin.Unit');
          const Function1 = Java.use('kotlin.jvm.functions.Function1');
          const FragmentHost = Java.use(
            'com.tencent.mobileqq.activity.QPublicFragmentActivity'
          );
          const PetMainFragment = Java.use(
            'com.tencent.mobileqq.qqpet.main.PetMainFragment'
          );
          const Sdk = Java.use('com.tencent.mobileqq.qqpet.sdk.a');
          const MobileQQ = Java.use('mqq.app.MobileQQ');

          let uin = '';
          try {
            uin = String(
              MobileQQ.sMobileQQ.value.peekAppRuntime().getCurrentAccountUin()
            );
          } catch (_) {}
          if (!/^\d{5,12}$/.test(uin)) {
            reject(new Error('无法读取当前登录 QQ'));
            return;
          }

          let activity = null;
          Java.choose('com.tencent.mobileqq.activity.SplashActivity', {
            onMatch: function (candidate) {
              if (!activity && !candidate.isFinishing() && !candidate.isDestroyed()) {
                try {
                  activity = Java.retain(candidate);
                } catch (_) {}
              }
            },
            onComplete: function () {
              if (!activity) {
                reject(new Error('没有找到 QQ 主界面，请先打开并登录手机 QQ'));
                return;
              }

              const Callback = Java.registerClass({
                name: 'com.tencent.mobileqq.qqpet.OpenPageCallback' + Date.now(),
                implements: [Function1],
                methods: {
                  invoke: function () {
                    Java.scheduleOnMainThread(function () {
                      try {
                        const intent = Intent.$new();
                        intent.putExtra('petUin', uin);
                        intent.putExtra('pageData', '{}');
                        intent.putExtra('from_adopt', false);
                        intent.putExtra('adopt_closing_pose_id', 0);
                        FragmentHost.start
                          .overload(
                            'android.content.Context',
                            'android.content.Intent',
                            'java.lang.Class'
                          )
                          .call(
                            FragmentHost,
                            activity,
                            intent,
                            PetMainFragment.class
                          );
                        resolve({ ok: true, uin: uin });
                      } catch (e) {
                        reject(e);
                      }
                    });
                    return Unit.INSTANCE.value;
                  },
                },
              });

              try {
                const sdkClass = Sdk.class;
                const singleton = sdkClass.getDeclaredField('a');
                singleton.setAccessible(true);
                const sdk = singleton.get(null);
                const initMethod = sdkClass.getDeclaredMethod(
                  'd',
                  Java.array('java.lang.Class', [Function1.class])
                );
                initMethod.setAccessible(true);
                initMethod.invoke(
                  sdk,
                  Java.array('java.lang.Object', [Callback.$new()])
                );
              } catch (e) {
                reject(new Error('SDK 初始化失败：' + (e.stack || String(e))));
              }
            },
          });
        } catch (e) {
          reject(e);
        }
      });
    });
  },
};
