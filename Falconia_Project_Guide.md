# Falconia — Mapping Fire, Revealing Patterns

## Hızlı başlangıç

1. ZIP’i çıkar; `Falconia_Template.html` dosyasını tarayıcıda aç.
2. Üstteki dünya haritasında bölge seç, haritayı sürükle, +/− ile yakınlaş. Klavyede oklar kaydırır, Home dünya görünümüne döner. Ctrl + tekerlek de yakınlaştırır.
3. **Günleri oynat** düğmesi kayıt bulunan günleri sırayla gösterir. Saat kontrolü seçili UTC gününde o saate kadar alınmış gözlemleri gösterir. **Tüm tarihler** toplam görünüme döner.
4. Noktayı seçerek sensör sayımlarını ve örnek kayıtları incele. **Seçimi ayrıntılı analizde aç** ile aynı seçimi alt bölümdeki eş alanlı ızgara, takvim, kayıt tablosu, kanıt notları ve dışa aktarmaya aktar.
5. TR/EN düğmesi dili değiştirir. Sunum düğmesi mevcut 7 ekranlık anlatımı açar; bu, PowerPoint veya video dosyası değildir.

**Varsayılan veri:** Kullanıcının terminal çıktısında görünür olan **10 gerçek satırın aktarımıdır: 5 MODIS + 5 S-NPP/VIIRS**. Tarihler 31 Ekim 2025 ve 31 Temmuz 2026’dır. Endonezya, Afrika ve Rusya’nın doğusu çevresinde koordinatlar vardır. Ara günlerde kayıt olmadığını veya yangın olmadığını göstermez. Tarihler yalnız görünür kesitin tarihidir; tüm arşivin başlangıç/bitişi bilinmiyor.

Son gösterilen indeks 11.088.621’dir. Sıfırdan başlayan kesintisiz indeks varsayımıyla 11.088.622 satıra işaret eder; tam dosya teslim edilmediği için bu sayı bağımsız sayılmadı. Tam arşiv pakette değildir. Örnek 10 satır, yapay üretilmiş küresel yangın verisi değildir. Orijinal kaynak CSV ile bağımsız doğrulama yapılmadı.

## Tabloya uygulanan veri sözleşmesi

| Gelen alan / sorun | Uygulanan işlem |
|---|---|
| `instrument=SNPP`, `satellite=SNPP` | Tutarlı eşleşmede `sensor=VIIRS`, `platform=S-NPP`; `instrument_platform_alias` bayrağı. Çelişkili platform reddedilir. |
| MODIS `Aqua` / `Terra` | Ayrı platform olarak korunur. |
| `confidence` içinde `0 38\n1 37\n2 69...` | Tek gözlem değeri olmadığı için bilinmiyor; `confidence_series_text` ve `confidence_unknown`. İlk sayı 38 bütün satırlara atanmaz. |
| Sağlam MODIS güveni | 0–100 değer olarak tutulur. |
| Sağlam VIIRS güveni | `l/n/h` veya `low/nominal/high` olarak tutulur. MODIS güveniyle ortak sayısal ölçeğe çevrilmez. |
| `brightness`, `bright_t31` ile birleştirilmiş VIIRS | Kaynak alanları `raw` içinde korunur. VIIRS ana sıcaklık aliası işaretlenir; kaynak şeması kontrol edilmeden MODIS bandıyla eşdeğer sayılmaz. `bright_t31` VIIRS I5 diye sessizce yeniden adlandırılmaz. |
| `acq_time=1` | `00:01 UTC`; `11` → `00:11 UTC`. Yerel saat değildir. |
| `Unnamed: 0` | Analitik özellik olarak kullanılmaz; özgün kayıtta tutulur. Tam tekrar kontrolünde dışarıda bırakılır. |
| `type` | 0: varsayılan bitki yangını; 1: aktif volkan; 2: diğer sabit kara kaynağı; 3: su üstü tespit. Kaynak ürünün çıkarımıdır, tutuşma nedeni değildir. |
| `version=61.03 / 2.00` | Geldiği biçimde korunur. Bu metinler tam ürün kimliği/işleme geçmişini tek başına doğrulamaz. Orijinal dosyanın metin sütunu tercih edilir. |
| Eksik FRP | `null`; sıfırla doldurulmaz. FRP, pikseldeki ışınımsal güçtür (MW), yanan hektar değildir. |

Her kaynak satırı `raw`, kaynak adı/satırı ve kalite bayraklarıyla saklanır. Koordinatı, UTC zamanı veya sensör/platform eşleşmesi geçersiz satırlar reddedilir ve sayılır. Güveni bozuk ama konumu/zamanı sağlam satırlar görünür kalır; standart/yüksek kalite filtresinde dışarıda kalır.

### `confidence` hatasını gerçekten düzeltmek

Bu çıktı, sütunun bir yerde `str(df['confidence'])` benzeri biçimde tek bir metne çevrilmiş olabileceğini düşündürüyor; `train.py` görülmeden sebep kesinleşmez. Mevcut kesitte kaybolan değerler geri üretilemez. Orijinal CSV’den yeniden oku, satır bazlı değerleri koru. Örneğin pandas kullanılıyorsa **kaynak yeniden okunduktan sonra**:

```python
df = pd.read_csv('original.csv', dtype={'acq_time': 'string', 'confidence': 'string', 'version': 'string'})
# str(df['confidence']) KULLANMA: bu bütün sütunu tek metne dönüştürür.
# Gerekirse satır bazlı dönüşüm:
df['confidence'] = df['confidence'].astype('string').str.strip()
df.to_csv('data.csv', index=False)
```

Zaten bozulmuş sütuna `.astype('string')` uygulamak kaybolmuş değerleri düzeltmez. `type` da kesin anız/piknik/sanayi nedeni etiketi olarak bir modele verilmemelidir. Bu paket bir neden tahmin modeli eğitmez; temizleme, görselleştirme ve belgeli kalibrasyon altyapısı sağlar.

## Büyük arşivi bağla

Python 3.10 veya üstü yeterlidir; veri hattı yalnız standart kütüphaneyi kullanır. ZIP’teki dosyaların bulunduğu klasörde:

```bash
python Falconia_Data.py ingest data.csv --db falconia.sqlite
python Falconia_Data.py serve --db falconia.sqlite
```

Birden fazla kaynak CSV için:

```bash
python Falconia_Data.py ingest modis.csv viirs.csv --db falconia.sqlite
```

Tarayıcıda **http://127.0.0.1:8765** aç. Aynı adreste açılan şablon arşive otomatik bağlanır. HTML’yi çift tıklayarak açtıysan **Tam arşivi bağla** bölümünde **Arşivi bağla** düğmesini kullan. Durdurmak için terminalde Ctrl+C.

Var olan veritabanı üzerine yazılmaz. Yeniden içe alma için `--db falconia_v2.sqlite` gibi yeni ad kullan ve sunucuyu o dosyayla başlat. CSV dosyaları değiştirilmez. İçe alma boyunca kaynak dosyaları düzenleme. Her dosyanın SHA-256 özeti, kabul/red/tekrar sayıları ve ilk 100 red örneği veritabanındaki denetim kaydına yazılır. UTF-8, BOM, virgül/noktalı virgül ve tırnaklı çok satırlı alanlar desteklenir. Örnek dosya bilerek bozuk güven alanını korur; veri doğrulama akışını göstermek içindir.

### Ölçek ve doğruluk

- CSV dosyası satır satır okunur; 11 milyon Python nesnesi bellekte biriktirilmez. SQLite diskte tutulur; ham kaynak ve indeksler ek disk alanı kullanır.
- Harita sorgusunda **eşleşen tüm tutulan gözlemler** coğrafi görsel hücrelere toplanır. 10 satırlık örnek veya rastgele bir örneklem, tam arşivmiş gibi gösterilmez.
- Görsel hücre boyutu görünüm ölçeğine göre değişir; bu hücreler eş alanlı değildir, yalnız çizimi hafifletir. İşaretin merkezi gözlem koordinatlarının ortalamasıdır; yangın merkezi veya sınırı değildir. Aynı hücrede birden fazla olay bulunabilir.
- Büyük dosyaların yükleme/sorgu süresi donanıma bağlıdır. **11 milyon gerçek satırla hız veya yük testi yapılmadı.** Yerel sorgu 25 saniye kaynak sınırına takılırsa alanı/dönemi daralt. Bu servis tek bilgisayarlık prototiptir; çok kullanıcılı üretim sunucusu değildir.
- Ayrıntılı tarayıcı analizi 100.000 gözleme kadar çalışır; bunun üzerindeki aktarım kesilerek örneklenmez, reddedilir ve daha dar seçim istenir. Doğrudan tarayıcı CSV/JSON yüklemesi ayrıca dosya başına 25 MB sınırındadır.
- Tarih filtresi UTC günlerini dahil eder. Oynatma yalnız mevcut günleri gösterir; boş günleri doldurmaz ve aralarda yangın yayıldığı varsayılmaz.
- Dünya haritası equirectangular (enlem/boylam) koordinatlarıyla çizilir. NASA GIBS Blue Marble yalnız coğrafi arka plandır; seçili tarihin yangın/satellit görüntüsü değildir. Ağ olmazsa koordinat ızgarası kalır. 180° tarih çizgisini geçen dar alanlar iki ayrı sorguya ayrılmalıdır.
- CSV’de `source_row` mantıksal kayıt sırasıdır; tırnak içinde yeni satır varsa fiziksel dosya satır numarasıyla aynı olmayabilir.

## Ana analize geçiş ve korunan bilimsel yöntem

Dünya panelindeki seçimi **Ayrıntılı analizde aç** ile alt panele aktar. Alt panel bağımsız seçim yapabilir; üstte arşiv bağlıyken alttaki örnek kendiliğinden tam arşiv olarak değiştirilmez. Hangi veriyle çalışıldığı iki panelde de yazılır.

- MODIS ve VIIRS ham gözlem sayıları ayrı tutulur; tespit sayısı yangın olayı sayısı değildir.
- Alt panel 1/2/5 km küresel eş alanlı CEA ızgarası ve UTC günleri kullanır. Bu küresel formül **EPSG:6933 değildir**. Bir hücre-gün, o gün en az bir tespit içeren hücredir.
- Tekrar silme yalnız aynı kaynak değerleri için yapılır. Ayrı sensörlerin yakın tespitleri bir yangınmış gibi silinmez. SQLite’da tekrar sayısı ve tekrar kaynak satırları ayrıca korunur.
- Ortak ızgara, sensör harmonizasyonunu tamamlamaz. Bunun için aynı geçerli gözlem maskesindeki tespitli hücre oranları, sabit platform grubu ve tarihsel örtüşme gerekir.
- Kalibrasyon paneli belgeli `metric_context` + `daily_metrics` JSON kabul eder. En az 80 eşleşmiş gün; en az 60 önceki eğitim ve 20 sonraki test günü; eğitimde en az 30 etkin gün gerekir. OLS düzeltmesi sonraki dönemde ham referanstan daha iyi MAE ve pozitif blok-bootstrap iyileşme aralığı göstermelidir. Geçerse **ön modeldir**; bağımsız ve mevsimsel doğrulama gerekir.
- Alan/ızgara/kalite/platform kapsamı değişince eski model geçersizleşir. Modelin eğitim girdisi aralığı dışına sessizce ekstrapolasyon yapılmaz.
- Mevsimsel bağlam için en az 3 önceki yıl, her yıl ±15 günlük pencerede en az 25 geçerli gözlem günü gerekir. Kapsam yoksa sonuç üretilmez. Bu bir tahmin değildir.
- Kaynaklı kanıt formu anız, sanayi, bitki örtüsü, atık/piknik, yıldırım, volkan ve yerleşim bağlamlarını araştırma hipotezi olarak saklar. Yetkili inceleme olmadan tutuşma nedeni kesinleştirilmez.

Günlük metrik örneği (yer tutucuları gerçek kaynakla değiştir; kaynak maskesi bu paket tarafından otomatik üretilmez):

```json
{
  "metric_context": {
    "target": "occupied_cell_fraction",
    "coverage_method": "common_valid_observation_mask",
    "grid_definition": "sphere-cea-30-v1",
    "grid_km": 2,
    "bbox": [26,36,45,42],
    "quality_filter": "all",
    "platforms": {"MODIS":["Aqua"],"VIIRS":["S-NPP"]},
    "platform_signature": "Aqua__S-NPP",
    "source_manifest": "YOUR_REAL_SOURCE_MANIFEST",
    "processing_code_url": "https://YOUR_PUBLIC_REPOSITORY"
  },
  "daily_metrics": [
    {"date":"2025-10-31","common_valid_cells":1000,"modis_occupied_cells":10,"viirs_occupied_cells":15,"platform_signature":"Aqua__S-NPP"}
  ]
}
```

Bu örnek sayılar sentetiktir; kalibrasyon sonucu veya maskesi değildir. Yer tutuculu ve yetersiz günlük paket, uygulamanın doğrulamasından geçmez.

## Mevcut siteye entegrasyon

`Falconia_Template.html` HTML, CSS, analiz çekirdeği, dünya modülü, kaynak belgeleri ve 10 satırlık örneği içerir. Çift tıklayarak açılır; Node kurulumu gerekmez. `Falconia_Data.py` yalnız büyük arşiv için gerekir.

API uçları:

| Uç | Sonuç |
|---|---|
| `/api/status` | Kaynak dosya özetleri, geçerli kayıt sayısı, tarih/koordinat kapsamı ve kalite denetimi. |
| `/api/view?bbox=-180,-90,180,90&start=2025-10-31&end=2026-07-31&sensor=ALL&quality=all&type=ALL` | Tüm eşleşmelerden görsel hücreler ve günlük sayımlar. `until=2026-07-31T23:59:00.000Z` UTC kesimi eklenebilir. |
| `/api/observations?...` | Aynı filtrelerle en fazla 100.000 ham/normalize gözlem; daha fazla ise hata. |

Statik siteyi yayımlamak için HTML yeterlidir; Python ve SQLite statik hostta çalışmaz. Tam arşiv hizmeti ayrı bir backend’e taşınmalı; bu yerel sunucu internete açık üretim servisi olarak sunulmamalıdır. Varsayılan adres yalnız 127.0.0.1’dir. Web arayüzündeki yerel bağlantı da localhost/127.0.0.1 ile sınırlandırılmıştır. Mevcut başka backend’e aktarırken aynı cevap şemasını koruyup bağlantı kodunu uyarlayın.

Özgün kayıt JSON’u ve kaynak notlarıyla dışa aktarılabilir. Notlar oturumda kalır; kanıt paketini indirmeden pencereyi kapatma. Harita görsel toplamaları ile ayrıntılı bilimsel toplamaları aynı metrik gibi raporlama.

## Jüri ve teslim

Kullanılabilecek açık anlatım: “Küresel koordinatları ve büyük CSV arşivlerini destekleyen bir gözlem inceleme sistemi kurduk. Veri şeması hatalarını işaretliyor, uydu gözlemlerini zaman içinde oynatıyor, ayrıntılı analizi kaynak kaydına bağlıyoruz. Şu an görülen kesit 10 satır; tam arşiv bağlanmadan küresel kapsama ve kalibrasyon başarısına ilişkin iddia yapmıyoruz.” Tam arşiv gerçekten bağlandığında sayıyı, tarih aralığını ve doğrulanmış sonuçları güncelle.

Sitedeki 12 jüri sorusu ve 7 ekranlık sunum korunur. Galactic Impact referansları ayrı inceleme belgesindedir; erişilemeyen siteler belirtilir. Kod/arayüz başka projelerden kopyalanmadı; genel ürün ilkelerinden yararlanıldı. Ödül veya dünya çapında benzersizlik garantisi yoktur.

Resmî proje formu, herkese açılan site/kod/demo bağlantıları, kaynak ve AI beyanı, uygun açık kaynak lisansı, güncel sunum kuralları ve yerel jüri süresi ekip tarafından tamamlanmalıdır. Web şablonu tek başına resmî teslim değildir. Geçmiş yarışma araştırması `Falconia_Reference_Audit.md` içindedir. AI beyanı ve kaynak atıfları görünür kalır; kişisel isimler yoktur.

## Doğrulama kapsamı

12 mevcut bilimsel çekirdek testi, 4 yeni şema/kesit testi ve 8 Python veri hattı testi çalıştırıldı. Ayrıca açılış, bölge/kalite/tür filtreleri, zaman kesimi, oynatma, ayrıntılı analize aktarım ve gerçek yerel HTTP servisine bağlantı mock DOM ile sınandı. Bu, görsel tarayıcı testi değildir. Tarayıcı oturumuna erişim hatası nedeniyle ekran görünümü ve gerçek fare/dokunma davranışı görsel olarak doğrulanamadı. Tam 11 milyon satırlık dosya sağlanmadığından o ölçekte performans testi yapılmadı.

## Kaynaklar

- [NASA FIRMS MODIS alan tanımları](https://firms.modaps.eosdis.nasa.gov/content/descriptions/FIRMS_MODIS_Firehotspots.html)
- [NASA FIRMS VIIRS alan tanımları](https://firms.modaps.eosdis.nasa.gov/content/descriptions/FIRMS_VIIRS_Firehotspots.html)
- [NASA FIRMS API eğitimi](https://firms.modaps.eosdis.nasa.gov/content/academy/data_api/firms_api_use.html)
- [NASA GIBS](https://nasa-gibs.github.io/gibs-api-docs/)
- [FIRMS tespit sınırları](https://firms.modaps.eosdis.nasa.gov/alerts/notes.php)
- [2026 Space Apps kaynak ve AI açıklamaları](https://github.com/nasa/spaceapps/discussions/2123)

AI-assisted interface, documentation and code. Supplied observation values were transcribed, not generated. The corrupted confidence text is retained as evidence of the supplied schema issue, not repaired by inference.
