/*
 * Fake DG-LAB 4gen App (JS bleInit sequence decoded):
 *   read 180A/1501(version), 180A/1500(power), 180A/2A25(sn)
 *   notify 1500, notify 180C/150B, check 180C/150A
 *   notify ff0a/ff00, check ff0a/ff01
 *   WRITE "6600..." to 180C/150A  -> device MUST notify "66..." on 150B within 2s
 * Logs everything; responds 66 to system-config request (and B1 for B0).
 */
#include <Arduino.h>
#include <BLE.h>

static const BLEUUID S_180C("0000180C-0000-1000-8000-00805F9B34FB");
static const BLEUUID C_150A("0000150A-0000-1000-8000-00805F9B34FB");
static const BLEUUID C_150B("0000150B-0000-1000-8000-00805F9B34FB");
static const BLEUUID S_180A("0000180A-0000-1000-8000-00805F9B34FB");
static const BLEUUID C_1500("00001500-0000-1000-8000-00805F9B34FB");
static const BLEUUID C_1501("00001501-0000-1000-8000-00805F9B34FB");
static const BLEUUID C_2A25("00002A25-0000-1000-8000-00805F9B34FB");
static const BLEUUID S_FF0A("0000FF0A-0000-1000-8000-00805F9B34FB");
static const BLEUUID C_FF00("0000FF00-0000-1000-8000-00805F9B34FB");
static const BLEUUID C_FF01("0000FF01-0000-1000-8000-00805F9B34FB");

static BLECharacteristic ch150A, ch150B;
static int intA=0, intB=0;

static String hexOf(const uint8_t*d,size_t len){
  String s=""; char b[4];
  for(size_t i=0;i<len;i++){ sprintf(b,"%02X",d[i]); s+=b; }
  return s;
}
static void notifyHex(BLECharacteristic &c,const char*hex){
  size_t len=strlen(hex)/2;
  uint8_t buf[40];
  for(size_t i=0;i<len;i++){ unsigned int v=0; sscanf(hex+2*i,"%2X",&v); buf[i]=(uint8_t)v; }
  c.setValue(buf,len);
  BTStatus st=c.notify();
  Serial.printf("  -> NOTIFY %s (ok=%d)\n",hex,(bool)st);
}

void setup(){
  Serial.begin(115200); delay(300);
  Serial.println("\n=== Fake DG-LAB 4gen (decoded bleInit) ===");

  BTStatus init=BLE.begin("47L121000");
  if(!init){ Serial.printf("begin FAIL %s\n",init.toString()); while(true)delay(1000);}
  BLEServer server=BLE.createServer();
  server.onConnect([](BLEServer s,const BLEConnInfo&c){
    Serial.printf("[CONNECT] %s MTU=%d\n",c.getAddress().toString().c_str(),c.getMTU());
  });
  server.onDisconnect([](BLEServer s,const BLEConnInfo&c,uint8_t r){
    Serial.printf("[DISCONNECT] reason=0x%02X\n",r); s.startAdvertising();
  });

  // ---- 180C: control ----
  BLEService v3=server.createService(S_180C);

  // 150A: WRITE + WRITE_NR (no READ)
  ch150A=v3.createCharacteristic(C_150A,
      BLEProperty::Write|BLEProperty::WriteNR, BLEPermission::WriteOpen);
  ch150A.setValue((uint8_t*)"\x00",1);
  ch150A.onWrite([](BLECharacteristic c,const BLEConnInfo&x){
    size_t len=0; const uint8_t*d=c.getValue(&len);
    String h=hexOf(d,len);
    Serial.printf("[WRITE 150A] len=%u HEX=%s\n",(unsigned)len,h.c_str());
    if(h.startsWith("66")){
      // system config request -> reply "66..." on 150B within 2s
      notifyHex(ch150B,"660000000000000000000000000000000000000000000000");
    } else if(h.startsWith("B0")){
      // stim command -> reply B1
      int a=0,b=0;
      if(len>=4){ a=d[2]; b=d[3]; }
      intA=a; intB=b;
      char b1[16]; sprintf(b1,"B100%02X%02X",intA,intB);
      notifyHex(ch150B,b1);
    } else {
      Serial.println("  (other 150A write)");
    }
  });

  // 150B: NOTIFY + READ
  ch150B=v3.createCharacteristic(C_150B,
      BLEProperty::Notify|BLEProperty::Read, BLEPermission::ReadOpen);
  ch150B.setValue((uint8_t*)"\xB1\x00\x00\x00",4);
  ch150B.onSubscribe([](BLECharacteristic c,const BLEConnInfo&x,uint16_t s){
    Serial.printf("[SUB 150B] %u\n",s);
  });
  ch150B.onRead([](BLECharacteristic c,const BLEConnInfo&x){ Serial.println("[R 150B]"); });

  // ---- 180A: device info + battery ----
  BLEService info=server.createService(S_180A);
  BLECharacteristic c1501=info.createCharacteristic(C_1501,BLEProperty::Read,BLEPermission::ReadOpen);
  uint8_t ver[2]={0x01,0x04}; c1501.setValue(ver,2);
  c1501.onRead([](BLECharacteristic c,const BLEConnInfo&x){ Serial.println("[R 1501 version]"); });

  BLECharacteristic c1500=info.createCharacteristic(C_1500,
      BLEProperty::Read|BLEProperty::Notify,BLEPermission::ReadOpen);
  uint8_t lv=100; c1500.setValue(&lv,1);
  c1500.onRead([](BLECharacteristic c,const BLEConnInfo&x){ Serial.println("[R 1500 power]"); });
  c1500.onSubscribe([](BLECharacteristic c,const BLEConnInfo&x,uint16_t s){
    Serial.printf("[SUB 1500] %u\n",s); });

  BLECharacteristic c2a25=info.createCharacteristic(C_2A25,BLEProperty::Read,BLEPermission::ReadOpen);
  uint8_t sn[8]={'4','7','L','1','2','1','0','0'}; c2a25.setValue(sn,8);
  c2a25.onRead([](BLECharacteristic c,const BLEConnInfo&x){ Serial.println("[R 2A25 SN]"); });

  // ---- ff0a: OTA check chars ----
  BLEService v4=server.createService(S_FF0A);
  BLECharacteristic f0=v4.createCharacteristic(C_FF00,
      BLEProperty::Write|BLEProperty::WriteNR|BLEProperty::Notify,BLEPermission::WriteOpen);
  f0.setValue((uint8_t*)"\x00",1);
  f0.onWrite([](BLECharacteristic c,const BLEConnInfo&x){
    size_t len=0; const uint8_t*d=c.getValue(&len);
    Serial.printf("[WRITE ff00] len=%u HEX=%s\n",(unsigned)len,hexOf(d,len).c_str());
  });
  f0.onSubscribe([](BLECharacteristic c,const BLEConnInfo&x,uint16_t s){
    Serial.printf("[SUB ff00] %u\n",s); });
  BLECharacteristic f1=v4.createCharacteristic(C_FF01,
      BLEProperty::Write|BLEProperty::WriteNR,BLEPermission::WriteOpen);
  f1.setValue((uint8_t*)"\x00",1);
  f1.onWrite([](BLECharacteristic c,const BLEConnInfo&x){
    size_t len=0; const uint8_t*d=c.getValue(&len);
    Serial.printf("[WRITE ff01] len=%u HEX=%s\n",(unsigned)len,hexOf(d,len).c_str());
  });

  BTStatus st=server.start();
  if(!st){ Serial.printf("start FAIL %s\n",st.toString()); while(true)delay(1000);}

  BLEAdvertising adv=BLE.getAdvertising();
  adv.setName("47L121000");
  adv.addServiceUUID(S_180C);
  adv.addServiceUUID(S_180A);
  adv.setScanResponse(true);
  st=adv.start();
  if(!st){ Serial.printf("adv FAIL %s\n",st.toString()); while(true)delay(1000);}
  Serial.println("[READY] 180C(150A W / 150B N) + 180A(1500/1501/2A25) + ff0a");
  Serial.println("[READY] Will reply 66 on system-config write...");
}

void loop(){ delay(1000); }
