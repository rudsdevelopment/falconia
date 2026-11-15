# Falconia — Mapping Fire, Revealing Patterns

Uydu yangın tespitlerini (NASA FIRMS MODIS + VIIRS) inceleyen, kaynak izini koruyan
ve büyük CSV arşivlerini yerel SQLite üzerinden sunan bir prototip.

- `Falconia_Template.html` — tek dosyalık site (HTML + CSS + analiz çekirdeği). Çift tıklayarak açılır.
- `Falconia_Data.py` — CSV doğrulama, SQLite arşivi ve yerel HTTP API (`/api/status`, `/api/view`, `/api/observations`).
- `Falconia_Project_Guide.md` — veri sözleşmesi, yöntem ve sınırlamalar.

## Hızlı başlangıç (sadece site)

`Falconia_Template.html` dosyasını tarayıcıda aç. 10 satırlık örnek veri gömülüdür;
Node veya sunucu gerekmez.

## Tam arşivi çalıştırma

Tam arşiv, GitHub deposuna değil **Releases** bölümüne yüklenir (tek dosya sınırı:
depo 100 MB, release 2 GB). İndirdikten sonra:

```bash
zstd -d falconia-compact.sqlite.zst          # .zst sürümünü aç
python Falconia_Data.py serve --db falconia-compact.sqlite
```

Tarayıcıda `http://127.0.0.1:8765` aç, **Tam arşivi bağla** bölümünde adresi gir ve
**Arşivi bağla** düğmesine bas.

## Kompakt arşivi kendin üret

```bash
python Falconia_Data.py ingest Falconia_Excerpt.csv --db falconia-compact.sqlite --compact
```

Kompakt biçim, satır başına ham CSV metnini (`raw`) saklamaz; koordinat/tarih/sensör
alanlarını ölçekli tamsayı ve kodlu enum olarak tutar. Kaynak dosyanın SHA-256 özeti,
kabul/red/tekrar sayıları ve `source_row` korunur. Tam tekrarlar sayılır ve atılır;
satır başına ham metin geri getirilemez. Ölçülen sonuç:

| Biçim | Boyut | Satır |
|---|---:|---:|
| Eski `raw` arşivi | ~4.55 GB | 13.676.796 |
| Kompakt SQLite | ~848 MB | 13.676.796 |
| Kompakt `.zst` | ~225 MB | 13.676.796 |

Kompakt arşiv aynı API yanıtlarını üretir; `serve` biçimi otomatik algılar. İsteğe
bağlı olarak daha küçük bir alt küme (ör. yüksek güvenli tespitler veya tek ay)
depoya sığacak şekilde ayrıca üretilebilir; bu bir **filtrelenmiş alt küme** olarak
etiketlenmelidir, tam arşiv sayılmaz.

## GitHub'a yayımlama

1. Boş bir depo oluştur (public olması GitHub Pages için gerekir).
2. Depoyu bağla ve gönder:

   ```bash
   git init -b main
   git add .
   git commit -m "Falconia archive viewer"
   git remote add origin https://github.com/KULLANICI/Falconia.git
   git push -u origin main
   ```

3. `.github/workflows/pages.yml` her `main` gönderiminde siteyi GitHub Pages'e yayımlar.
   Depo **Settings → Pages → Source** ayarını **GitHub Actions** yap.
4. Büyük arşivi Release'e yükle (GitHub CLI gerekir):

   ```bash
   gh release create v2.0.0 \
     falconia-compact.sqlite \
     falconia-compact.sqlite.zst \
     falconia-compact.sqlite.sha256 \
     --title "Falconia compact archive v2.0.0" \
     --notes "13.676.796 satır. İndir, zstd -d ile aç, python Falconia_Data.py serve --db falconia-compact.sqlite"
   ```

   Veya GitHub web arayüzünde **Releases → Draft a new release** ile dosyaları elle yükle.

Bütünlük kontrolü:

```bash
sha256sum -c falconia-compact.sqlite.sha256
```

## Sınırlar

- GitHub Pages yalnız statik dosya sunar; Python/SQLite API'si Pages üzerinde çalışmaz.
  Tam arşiv yerel olarak indirilip çalıştırılır. Canlı çok kullanıcılı sunucu değildir.
- Hotspot tespiti bağımsız yangın olayı veya yanan alan değildir; kapsam bilinmiyorsa
  sıfır etkinlik varsayılmaz.
- Kompakt modda ham satır metni saklanmaz. Tam ham veri gerekiyorsa orijinal CSV'yi
  sakla; SHA-256 özeti ve `source_row` eşleştirmesi bunun içindir.
- AI beyanı ve kaynak atıfları görünür kalır. Kaynak gözlem değerleri AI ile üretilmedi.

## Lisans

Açık kaynak lisansı ekip tarafından seçilip eklenmelidir (teslim koşulları gereği).
