# dashboard-saham

Dashboard Streamlit untuk analisa saham IDX (teknikal + fundamental), watchlist, dan jurnal transaksi.

## Setup

```
pip install -r requirements.txt
streamlit run dashboard_saham.py
```

## Auto-backup jurnal transaksi ke GitHub (opsional)

Jurnal transaksi disimpan di SQLite lokal (`jurnal_saham.db`), yang **tidak
persisten** di Streamlit Community Cloud — bisa hilang saat container
di-redeploy/reset. Supaya data tidak hilang, ada dua lapis backup:

1. **Manual** — tombol "Download Jurnal sebagai CSV" di tab Jurnal Transaksi, tidak butuh setup apa pun.
2. **Otomatis ke GitHub** — tiap ada transaksi baru/dihapus, app akan commit+push snapshot CSV (`jurnal_saham_backup.csv`) ke repo ini. Untuk mengaktifkan:
   1. Buat GitHub Personal Access Token (classic) dengan scope `repo`, atau fine-grained token dengan akses "Contents: Read and write" ke repo ini.
   2. Di Streamlit Community Cloud: buka app ini → **Settings → Secrets**, lalu tambahkan:
      ```
      GITHUB_TOKEN = "ghp_xxxxxxxxxxxxxxxx"
      ```
   3. Simpan — app akan otomatis reboot dan auto-backup langsung aktif (status-nya kelihatan di tab Jurnal Transaksi).

Kalau `GITHUB_TOKEN` belum diset, auto-backup otomatis dilewati (tidak bikin app error) — backup manual via tombol download tetap selalu tersedia.
