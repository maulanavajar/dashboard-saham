"""
Dashboard Streamlit - Analisa Saham (Teknikal + Fundamental Dasar)
====================================================================
Kebutuhan: pip install streamlit yfinance pandas ta plotly

Cara jalankan:
    python -m streamlit run dashboard_saham.py
"""

import subprocess
import sqlite3
from datetime import date

import pandas as pd
import streamlit as st
import yfinance as yf
import ta
import plotly.graph_objects as go


# ---------- Database Jurnal Transaksi (SQLite) ----------

DB_PATH = "jurnal_saham.db"
BACKUP_CSV_PATH = "jurnal_saham_backup.csv"


def init_db():
    """Buat tabel transaksi kalau belum ada."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS transaksi (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tanggal TEXT NOT NULL,
            kode TEXT NOT NULL,
            aksi TEXT NOT NULL,
            harga REAL NOT NULL,
            lot INTEGER NOT NULL,
            alasan TEXT
        )
    """)
    conn.commit()
    conn.close()


def tambah_transaksi(tanggal, kode, aksi, harga, lot, alasan):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO transaksi (tanggal, kode, aksi, harga, lot, alasan) VALUES (?, ?, ?, ?, ?, ?)",
        (str(tanggal), kode, aksi, harga, lot, alasan),
    )
    conn.commit()
    conn.close()


def ambil_semua_transaksi() -> pd.DataFrame:
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM transaksi ORDER BY tanggal DESC, id DESC", conn)
    conn.close()
    return df


def hapus_transaksi(id_transaksi: int):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM transaksi WHERE id = ?", (id_transaksi,))
    conn.commit()
    conn.close()


def backup_csv_ke_git():
    """
    Export seluruh jurnal transaksi ke CSV lalu commit+push ke repo GitHub.

    SQLite di Streamlit Community Cloud TIDAK persisten (bisa hilang saat
    container di-redeploy/reset), jadi ini jadi lapisan pengaman supaya data
    transaksi tidak hilang.

    Butuh secret `GITHUB_TOKEN` (Personal Access Token dengan izin "repo")
    yang diset lewat menu App settings > Secrets di Streamlit Cloud:

        GITHUB_TOKEN = "ghp_xxxxxxxxxxxxxxxx"

    Kalau secret belum diset, fungsi ini diam-diam skip (tidak bikin transaksi
    gagal tersimpan / tidak bikin app error) — jadi aman dipakai di lokal juga.
    """
    try:
        token = st.secrets.get("GITHUB_TOKEN")
    except Exception:
        token = None

    if not token:
        return False, "GITHUB_TOKEN belum diset — auto-backup dilewati."

    try:
        df = ambil_semua_transaksi()
        df.to_csv(BACKUP_CSV_PATH, index=False)

        remote_url = f"https://x-access-token:{token}@github.com/maulanavajar/dashboard-saham.git"

        subprocess.run(["git", "config", "user.email", "bot@dashboard-saham.local"], check=False, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Dashboard Saham Bot"], check=False, capture_output=True)
        subprocess.run(["git", "add", BACKUP_CSV_PATH], check=False, capture_output=True)

        commit = subprocess.run(
            ["git", "commit", "-m", f"chore: auto-backup jurnal transaksi ({date.today()})"],
            capture_output=True, text=True,
        )
        if commit.returncode != 0:
            # Kemungkinan besar "nothing to commit" (data sama persis) — bukan error.
            if "nothing to commit" in (commit.stdout + commit.stderr).lower():
                return True, "Tidak ada perubahan baru untuk di-backup."
            return False, f"Gagal commit: {commit.stderr.strip()}"

        push = subprocess.run(
            ["git", "push", remote_url, "HEAD:main"],
            capture_output=True, text=True,
        )
        if push.returncode != 0:
            return False, f"Gagal push ke GitHub: {push.stderr.strip()}"

        return True, "Backup CSV berhasil di-push ke GitHub."
    except Exception as e:
        # Backup gagal tidak boleh bikin transaksi utama gagal tersimpan.
        return False, f"Auto-backup gagal: {e}"


def hitung_ringkasan_pl(df: pd.DataFrame) -> pd.DataFrame:
    """Hitung profit/loss sederhana per kode saham (FIFO simplifikasi: total beli vs total jual)."""
    if df.empty:
        return pd.DataFrame()

    hasil = []
    for kode, grup in df.groupby("kode"):
        beli = grup[grup["aksi"] == "Beli"]
        jual = grup[grup["aksi"] == "Jual"]

        total_lot_beli = beli["lot"].sum()
        total_lot_jual = jual["lot"].sum()
        nilai_beli = (beli["harga"] * beli["lot"]).sum()
        nilai_jual = (jual["harga"] * jual["lot"]).sum()

        avg_beli = nilai_beli / total_lot_beli if total_lot_beli > 0 else 0
        avg_jual = nilai_jual / total_lot_jual if total_lot_jual > 0 else 0

        # P/L direalisasi hanya dari lot yang sudah dijual
        lot_terealisasi = min(total_lot_beli, total_lot_jual)
        pl_realisasi = (avg_jual - avg_beli) * lot_terealisasi if lot_terealisasi > 0 else 0
        lot_masih_dipegang = total_lot_beli - total_lot_jual

        hasil.append({
            "Kode": kode,
            "Total Lot Beli": total_lot_beli,
            "Total Lot Jual": total_lot_jual,
            "Lot Masih Dipegang": lot_masih_dipegang,
            "Avg Harga Beli": round(avg_beli, 2),
            "Avg Harga Jual": round(avg_jual, 2) if total_lot_jual > 0 else "-",
            "P/L Realisasi (Rp)": round(pl_realisasi, 2),
        })

    return pd.DataFrame(hasil)


# ---------- Fungsi-fungsi analisa (sama seperti analisa_saham.py) ----------

@st.cache_data(ttl=900, show_spinner=False)  # cache 15 menit
def ambil_data(ticker: str, period: str = "6mo", interval: str = "1d") -> pd.DataFrame:
    df = yf.download(ticker, period=period, interval=interval, progress=False)
    if df.empty:
        raise ValueError(f"Data untuk {ticker} tidak ditemukan. Cek kode tickernya.")
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    return df


def hitung_indikator(df: pd.DataFrame) -> pd.DataFrame:
    df["MA20"] = df["Close"].rolling(window=20).mean()
    df["MA50"] = df["Close"].rolling(window=50).mean()
    df["RSI"] = ta.momentum.RSIIndicator(close=df["Close"], window=14).rsi()
    macd = ta.trend.MACD(close=df["Close"])
    df["MACD"] = macd.macd()
    df["MACD_Signal"] = macd.macd_signal()

    # Bollinger Bands - mengukur volatilitas & area jenuh beli/jual
    bb = ta.volatility.BollingerBands(close=df["Close"], window=20, window_dev=2)
    df["BB_Upper"] = bb.bollinger_hband()
    df["BB_Lower"] = bb.bollinger_lband()
    df["BB_Mid"] = bb.bollinger_mavg()

    # Stochastic Oscillator - momentum, mirip RSI tapi lebih sensitif
    stoch = ta.momentum.StochasticOscillator(
        high=df["High"], low=df["Low"], close=df["Close"], window=14, smooth_window=3
    )
    df["Stoch_K"] = stoch.stoch()
    df["Stoch_D"] = stoch.stoch_signal()

    return df


def hitung_pivot_point(df: pd.DataFrame) -> dict:
    last = df.iloc[-1]
    high, low, close = last["High"], last["Low"], last["Close"]
    pivot = (high + low + close) / 3
    r1 = (2 * pivot) - low
    r2 = pivot + (high - low)
    s1 = (2 * pivot) - high
    s2 = pivot - (high - low)
    return {
        "Pivot": round(pivot, 2),
        "Resistance 1": round(r1, 2),
        "Resistance 2": round(r2, 2),
        "Support 1": round(s1, 2),
        "Support 2": round(s2, 2),
    }


def _deteksi_level_swing(df: pd.DataFrame, window: int = 5, toleransi_persen: float = 1.5) -> dict:
    """Fungsi inti deteksi swing support/resistance, return level RAW (angka) + jumlah sentuhan."""
    recent = df.tail(90).copy()
    swing_lows, swing_highs = [], []
    lows = recent["Low"].values
    highs = recent["High"].values

    for i in range(window, len(recent) - window):
        if lows[i] == min(lows[i - window:i + window + 1]):
            swing_lows.append(lows[i])
        if highs[i] == max(highs[i - window:i + window + 1]):
            swing_highs.append(highs[i])

    def kelompokkan_level(titik_titik, toleransi_persen):
        if not titik_titik:
            return []
        titik_terurut = sorted(titik_titik)
        kelompok = [[titik_terurut[0]]]
        for t in titik_terurut[1:]:
            rata_kelompok_terakhir = sum(kelompok[-1]) / len(kelompok[-1])
            if abs(t - rata_kelompok_terakhir) / rata_kelompok_terakhir * 100 <= toleransi_persen:
                kelompok[-1].append(t)
            else:
                kelompok.append([t])
        hasil = [(round(sum(k) / len(k), 2), len(k)) for k in kelompok]
        return sorted(hasil, key=lambda x: x[1], reverse=True)

    level_support = kelompokkan_level(swing_lows, toleransi_persen)
    level_resistance = kelompokkan_level(swing_highs, toleransi_persen)

    return {
        "support_level": level_support[0][0] if level_support else None,
        "support_sentuhan": level_support[0][1] if level_support else 0,
        "resistance_level": level_resistance[0][0] if level_resistance else None,
        "resistance_sentuhan": level_resistance[0][1] if level_resistance else 0,
    }


def cari_swing_support_resistance(df: pd.DataFrame, window: int = 5, toleransi_persen: float = 1.5) -> dict:
    """
    Deteksi level support/resistance berdasarkan titik-titik swing high/low
    yang paling sering 'disentuh' harga (bukan cuma min/max mentah).

    Cara kerja:
    1. Cari swing low/high lokal (titik yang lebih rendah/tinggi dari tetangganya).
    2. Kelompokkan titik-titik yang berdekatan (dalam toleransi %) jadi satu level.
    3. Level dengan jumlah sentuhan terbanyak = level paling kuat.
    """
    raw = _deteksi_level_swing(df, window, toleransi_persen)

    hasil = {}
    if raw["support_level"] is not None:
        hasil["Support Terkuat (90 hari)"] = f"{raw['support_level']} (disentuh {raw['support_sentuhan']}x)"
    else:
        hasil["Support Terkuat (90 hari)"] = "-"

    if raw["resistance_level"] is not None:
        hasil["Resistance Terkuat (90 hari)"] = f"{raw['resistance_level']} (disentuh {raw['resistance_sentuhan']}x)"
    else:
        hasil["Resistance Terkuat (90 hari)"] = "-"

    return hasil


def hitung_sl_tp(close: float, support: float, resistance: float, buffer_persen: float = 1.0) -> dict:
    """
    Hitung Stop Loss & Take Profit berdasarkan Support/Resistance, dengan buffer,
    plus Risk-Reward Ratio-nya. Buffer mengantisipasi 'fakeout' (harga sedikit
    menembus level sebelum benar-benar mantul/gagal mantul).
    """
    sl = support * (1 - buffer_persen / 100)
    tp = resistance * (1 - buffer_persen / 100)  # sedikit di bawah resistance, lebih realistis

    risiko = close - sl
    potensi_untung = tp - close

    if risiko <= 0 or potensi_untung <= 0:
        # Harga sudah di luar range Support-Resistance yang wajar untuk dihitung.
        # Dibedakan sebabnya biar pesannya actionable, bukan cuma "N/A".
        if risiko <= 0:
            alasan = "harga saat ini sudah di bawah/sama dengan level Stop Loss yang dihitung"
        else:
            alasan = "harga saat ini sudah di atas/sama dengan level Take Profit yang dihitung (target sudah tercapai)"

        return {
            "SL": round(sl, 2),
            "TP": round(tp, 2),
            "Risiko (Rp)": round(risiko, 2),
            "Potensi Untung (Rp)": round(potensi_untung, 2),
            "Risk-Reward Ratio": "N/A (harga di luar range S/R)",
            "alasan_tidak_valid": alasan,
            "valid": False,
        }

    rr_ratio = potensi_untung / risiko

    return {
        "SL": round(sl, 2),
        "TP": round(tp, 2),
        "Risiko (Rp)": round(risiko, 2),
        "Risiko (%)": round(risiko / close * 100, 2),
        "Potensi Untung (Rp)": round(potensi_untung, 2),
        "Potensi Untung (%)": round(potensi_untung / close * 100, 2),
        "Risk-Reward Ratio": f"1 : {round(rr_ratio, 2)}",
        "rr_value": round(rr_ratio, 2),
        "valid": True,
    }


@st.cache_data(ttl=3600, show_spinner=False)  # cache 1 jam, fundamental jarang berubah
def ambil_fundamental(ticker: str) -> dict:
    """
    Ambil data fundamental dari Yahoo Finance.

    `.info` sering gagal "diam-diam" (Yahoo kadang balikin dict kosong/minim
    tanpa melempar exception, terutama kalau kena rate-limit di shared IP
    Streamlit Cloud) — sebelumnya ini bikin semua field tampil "-" tanpa
    penjelasan sama sekali. Sekarang kegagalan itu dikembalikan lewat key
    "_error" supaya bisa ditampilkan ke user, bukan cuma diam.
    """
    default = {
        "Nama": "-", "Sektor": "-", "PER (Trailing)": "-", "PBV": "-",
        "EPS (Trailing)": "-", "ROE": "-", "Dividend Yield": "-", "Market Cap": "-",
    }

    try:
        info = yf.Ticker(ticker).info
    except Exception as e:
        return {**default, "_error": f"Gagal mengambil data fundamental dari Yahoo Finance: {e}"}

    # Yahoo kadang balikin dict kosong/hampir kosong tanpa error saat API-nya
    # bermasalah (bukan exception) — di situ .get() akan selalu jatuh ke "-".
    if not info or len(info) <= 2:
        return {
            **default,
            "_error": (
                "Yahoo Finance tidak mengembalikan data fundamental untuk ticker ini "
                "(kemungkinan rate limit sementara atau perubahan di API mereka). "
                "Data teknikal (chart, indikator) tidak terpengaruh karena pakai endpoint "
                "berbeda. Coba klik 'Refresh Data' beberapa saat lagi."
            ),
        }

    return {
        "Nama": info.get("longName", "-"),
        "Sektor": info.get("sector", "-"),
        "PER (Trailing)": info.get("trailingPE", "-"),
        "PBV": info.get("priceToBook", "-"),
        "EPS (Trailing)": info.get("trailingEps", "-"),
        "ROE": info.get("returnOnEquity", "-"),
        "Dividend Yield": info.get("dividendYield", "-"),
        "Market Cap": info.get("marketCap", "-"),
    }


def buat_chart(df: pd.DataFrame, ticker: str, pivot: dict) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=df.index, open=df["Open"], high=df["High"],
        low=df["Low"], close=df["Close"], name="Harga"
    ))
    fig.add_trace(go.Scatter(x=df.index, y=df["MA20"], name="MA20", line=dict(width=1)))
    fig.add_trace(go.Scatter(x=df.index, y=df["MA50"], name="MA50", line=dict(width=1)))
    fig.add_trace(go.Scatter(
        x=df.index, y=df["BB_Upper"], name="BB Upper",
        line=dict(width=1, dash="dot", color="rgba(150,150,150,0.6)")
    ))
    fig.add_trace(go.Scatter(
        x=df.index, y=df["BB_Lower"], name="BB Lower",
        line=dict(width=1, dash="dot", color="rgba(150,150,150,0.6)"),
        fill="tonexty", fillcolor="rgba(150,150,150,0.08)"
    ))

    # Catatan: level Pivot/Resistance/Support sering berdekatan nilainya, jadi
    # kalau tiap garis dikasih annotation_text sendiri-sendiri, labelnya numpuk
    # jadi satu blok teks yang tidak terbaca. Solusinya: garis putus-putus tanpa
    # label per-garis (dibedakan dari warna), sementara angka detailnya sudah
    # ditampilkan rapi sebagai teks di bawah chart (section "Pivot Point").
    for label, harga in pivot.items():
        warna = "green" if "Support" in label else "red" if "Resistance" in label else "gray"
        fig.add_hline(y=harga, line_dash="dot", line_color=warna, line_width=1)

    fig.update_layout(
        title=f"Analisa Teknikal - {ticker}",
        xaxis_rangeslider_visible=False,
        height=600,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    )
    return fig


def bersihkan_kode(kode: str) -> str:
    """Rapikan satu kode saham: uppercase & tambahkan .JK kalau belum ada."""
    kode = kode.strip().upper()
    if kode and not kode.endswith(".JK"):
        kode += ".JK"
    return kode


def ringkasan_satu_saham(ticker: str, period: str = "6mo") -> dict:
    """Hitung ringkasan satu saham untuk ditampilkan di tabel watchlist."""
    df = ambil_data(ticker, period=period)
    df = hitung_indikator(df)
    pivot = hitung_pivot_point(df)
    last = df.iloc[-1]
    close = last["Close"]

    jarak_ke_support1 = round((close - pivot["Support 1"]) / close * 100, 2)
    jarak_ke_resistance1 = round((pivot["Resistance 1"] - close) / close * 100, 2)

    if last["RSI"] >= 70:
        sinyal_rsi = "Overbought"
    elif last["RSI"] <= 30:
        sinyal_rsi = "Oversold"
    else:
        sinyal_rsi = "Netral"

    return {
        "Kode": ticker.replace(".JK", ""),
        "Close": round(close, 2),
        "RSI(14)": round(last["RSI"], 2),
        "Sinyal RSI": sinyal_rsi,
        "Support 1": pivot["Support 1"],
        "Resistance 1": pivot["Resistance 1"],
        "Jarak ke Support (%)": jarak_ke_support1,
        "Jarak ke Resistance (%)": jarak_ke_resistance1,
        "Tren (MA20 vs MA50)": "Bullish" if last["MA20"] > last["MA50"] else "Bearish",
    }


# ---------- UI Streamlit ----------

init_db()

st.set_page_config(page_title="Analisa Saham", layout="wide")
st.title("📊 Dashboard Analisa Saham")

tab_detail, tab_watchlist, tab_jurnal = st.tabs(["🔍 Analisa Detail", "⭐ Watchlist", "📒 Jurnal Transaksi"])

# ===================== TAB 1: ANALISA DETAIL =====================
with tab_detail:
    with st.sidebar:
        st.header("Pengaturan - Analisa Detail")
        kode_input = st.text_input("Kode Saham (contoh: BBCA, BBRI, TLKM)", value="BBCA")
        period = st.selectbox("Periode Data", ["3mo", "6mo", "1y", "2y"], index=1)
        tombol = st.button("Analisa Sekarang", type="primary")

        if st.button("🔄 Refresh Data (paksa ambil ulang)"):
            st.cache_data.clear()
            st.success("Cache dibersihkan, data akan diambil ulang.")

        ticker = bersihkan_kode(kode_input)

    if tombol or ticker:
        try:
            with st.spinner(f"Mengambil data {ticker}..."):
                df = ambil_data(ticker, period=period)
                df = hitung_indikator(df)
                pivot = hitung_pivot_point(df)
                swing = cari_swing_support_resistance(df)
                fundamental = ambil_fundamental(ticker)

            st.subheader(f"Hasil Analisa: {ticker}")

            # Chart
            fig = buat_chart(df, ticker, pivot)
            st.plotly_chart(fig, use_container_width=True)
            st.caption(
                "Garis putus-putus: 🔴 Resistance · 🟢 Support · ⚪ Pivot — "
                "angka lengkapnya ada di bawah (Pivot Point & Support/Resistance Historis)."
            )

            col1, col2, col3 = st.columns(3)

            with col1:
                st.markdown("**Pivot Point (harian)**")
                for k, v in pivot.items():
                    st.write(f"{k}: `{v}`")

            with col2:
                st.markdown("**Support/Resistance Historis**")
                for k, v in swing.items():
                    st.write(f"{k}: `{v}`")

                st.markdown("**Indikator Teknikal**")
                last = df.iloc[-1]
                st.write(f"Close: `{last['Close']:.2f}`")
                st.write(f"MA20: `{last['MA20']:.2f}` | MA50: `{last['MA50']:.2f}`")
                st.write(f"RSI(14): `{last['RSI']:.2f}`")
                st.write(f"MACD: `{last['MACD']:.4f}` | Signal: `{last['MACD_Signal']:.4f}`")
                st.write(f"Stochastic %K: `{last['Stoch_K']:.2f}` | %D: `{last['Stoch_D']:.2f}`")

                if last["Close"] >= last["BB_Upper"]:
                    status_bb = "⚠️ Di atas Upper Band (jenuh beli)"
                elif last["Close"] <= last["BB_Lower"]:
                    status_bb = "⚠️ Di bawah Lower Band (jenuh jual)"
                else:
                    status_bb = "Normal (dalam band)"
                st.write(f"Bollinger Bands: `{status_bb}`")

            with col3:
                st.markdown("**Fundamental Dasar**")
                error_fundamental = fundamental.get("_error")
                for k, v in fundamental.items():
                    if k == "_error":
                        continue
                    st.write(f"{k}: `{v}`")
                if error_fundamental:
                    st.warning(error_fundamental)

            st.divider()
            st.subheader("🎯 Kalkulator Stop Loss / Take Profit")
            st.caption(
                "Perhitungan otomatis berdasarkan Support/Resistance. "
                "Bukan rekomendasi trading — gunakan sebagai salah satu pertimbangan saja."
            )

            colA, colB = st.columns(2)
            with colA:
                sumber_level = st.radio(
                    "Sumber level Support/Resistance",
                    ["Pivot Point (harian)", "Support/Resistance Historis (90 hari)"],
                    key="sumber_sltp",
                )
            with colB:
                buffer = st.slider(
                    "Buffer (%) — antisipasi fakeout",
                    min_value=0.0, max_value=5.0, value=1.0, step=0.5,
                    key="buffer_sltp",
                )

            raw_swing = _deteksi_level_swing(df)

            if sumber_level == "Pivot Point (harian)":
                support_dipakai = pivot["Support 1"]
                resistance_dipakai = pivot["Resistance 1"]
            else:
                support_dipakai = raw_swing["support_level"]
                resistance_dipakai = raw_swing["resistance_level"]

            if support_dipakai is None or resistance_dipakai is None:
                st.warning("Level Support/Resistance historis belum terdeteksi untuk saham ini, coba pakai Pivot Point.")
            else:
                hasil_sltp = hitung_sl_tp(last["Close"], support_dipakai, resistance_dipakai, buffer)

                colC, colD, colE, colF = st.columns(4)
                colC.metric("Stop Loss", f"Rp {hasil_sltp['SL']:,.2f}")
                colD.metric("Take Profit", f"Rp {hasil_sltp['TP']:,.2f}")

                if hasil_sltp["valid"]:
                    colE.metric("Risiko", f"{hasil_sltp['Risiko (%)']}%", delta=f"-Rp{hasil_sltp['Risiko (Rp)']:,.0f}", delta_color="inverse")
                    colF.metric("Potensi Untung", f"{hasil_sltp['Potensi Untung (%)']}%", delta=f"+Rp{hasil_sltp['Potensi Untung (Rp)']:,.0f}")

                    st.write(f"**Risk-Reward Ratio: `{hasil_sltp['Risk-Reward Ratio']}`**")
                    if hasil_sltp["rr_value"] >= 2:
                        st.success("✅ Rasio ≥ 1:2 — secara matematis cukup baik (potensi untung jauh lebih besar dari risiko).")
                    elif hasil_sltp["rr_value"] >= 1:
                        st.warning("⚠️ Rasio antara 1:1 - 1:2 — cukup, tapi bukan yang ideal.")
                    else:
                        st.error("🚫 Rasio di bawah 1:1 — potensi risiko lebih besar dari potensi untung, pertimbangkan ulang.")
                else:
                    st.error(
                        f"⚠️ Risk-Reward Ratio tidak bisa dihitung — {hasil_sltp['alasan_tidak_valid']}. "
                        f"Coba ganti sumber level ke "
                        f"'{'Support/Resistance Historis (90 hari)' if sumber_level == 'Pivot Point (harian)' else 'Pivot Point (harian)'}' "
                        f"di atas, atau tunggu harga kembali masuk ke range Support-Resistance."
                    )

        except Exception as e:
            st.error(f"Terjadi error: {e}")

# ===================== TAB 2: WATCHLIST =====================
with tab_watchlist:
    st.subheader("Ringkasan Watchlist")
    st.caption("Masukkan beberapa kode saham dipisah koma, contoh: BBCA, BBRI, TLKM, ANTM")

    input_watchlist = st.text_input(
        "Daftar Saham",
        value="BBCA, BBRI, TLKM",
        key="watchlist_input",
    )
    cek_watchlist = st.button("Cek Watchlist", type="primary")

    if cek_watchlist and input_watchlist.strip():
        daftar_kode = [bersihkan_kode(k) for k in input_watchlist.split(",") if k.strip()]

        hasil = []
        progress = st.progress(0, text="Memulai...")
        for i, kode in enumerate(daftar_kode):
            try:
                progress.progress((i + 1) / len(daftar_kode), text=f"Mengambil data {kode}...")
                hasil.append(ringkasan_satu_saham(kode))
            except Exception as e:
                st.warning(f"Gagal ambil data {kode}: {e}")
        progress.empty()

        if hasil:
            df_hasil = pd.DataFrame(hasil)

            def warnai_sinyal(val):
                if val == "Overbought":
                    return "color: red"
                elif val == "Oversold":
                    return "color: green"
                return ""

            def warnai_tren(val):
                return "color: green" if val == "Bullish" else "color: red"

            # Tanpa .format() eksplisit, Styler pandas menampilkan angka float
            # dengan banyak desimal (mis. "6375.000000") walaupun nilainya
            # sudah dibulatkan — jadi presisi tampilan diatur manual di sini.
            format_kolom = {
                "Close": "{:.2f}",
                "RSI(14)": "{:.2f}",
                "Support 1": "{:.2f}",
                "Resistance 1": "{:.2f}",
                "Jarak ke Support (%)": "{:.2f}%",
                "Jarak ke Resistance (%)": "{:.2f}%",
            }
            styled = df_hasil.style.map(warnai_sinyal, subset=["Sinyal RSI"]) \
                                    .map(warnai_tren, subset=["Tren (MA20 vs MA50)"]) \
                                    .format(format_kolom)

            st.dataframe(styled, use_container_width=True, hide_index=True)
            st.caption(
                "💡 'Jarak ke Support' kecil = harga dekat support (potensi area beli). "
                "'Jarak ke Resistance' kecil = harga dekat resistance (potensi area jual/profit taking)."
            )
        else:
            st.error("Tidak ada data yang berhasil diambil.")

# ===================== TAB 3: JURNAL TRANSAKSI =====================
with tab_jurnal:
    st.subheader("Catat Transaksi")

    with st.form("form_transaksi", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            kode_transaksi = st.text_input("Kode Saham (contoh: BBCA)")
            tanggal_transaksi = st.date_input("Tanggal", value=date.today())
        with c2:
            aksi = st.selectbox("Aksi", ["Beli", "Jual"])
            harga_transaksi = st.number_input("Harga per Lembar (Rp)", min_value=0.0, step=1.0)
        with c3:
            lot_transaksi = st.number_input("Jumlah Lot", min_value=1, step=1)
            alasan_transaksi = st.text_input("Alasan (opsional)", placeholder="misal: harga di Support 1")

        simpan = st.form_submit_button("Simpan Transaksi", type="primary")

        if simpan:
            if not kode_transaksi.strip():
                st.error("Kode saham wajib diisi.")
            else:
                kode_bersih = kode_transaksi.strip().upper().replace(".JK", "")
                tambah_transaksi(
                    tanggal_transaksi, kode_bersih, aksi,
                    harga_transaksi, int(lot_transaksi), alasan_transaksi
                )
                st.success(f"Transaksi {aksi} {kode_bersih} berhasil disimpan.")
                backup_csv_ke_git()  # best-effort, tidak mengganggu kalau gagal/belum dikonfigurasi

    st.divider()
    st.subheader("Ringkasan Profit/Loss per Saham")

    df_transaksi = ambil_semua_transaksi()

    if df_transaksi.empty:
        st.info("Belum ada transaksi yang dicatat.")
    else:
        # SQLite di Streamlit Community Cloud tidak persisten (bisa reset saat
        # container di-redeploy), jadi selalu sediakan cara backup manual —
        # ini tidak butuh konfigurasi apa pun, beda dengan auto-backup di atas.
        st.download_button(
            "⬇️ Download Jurnal sebagai CSV (backup manual)",
            data=df_transaksi.to_csv(index=False).encode("utf-8"),
            file_name=f"jurnal_saham_{date.today()}.csv",
            mime="text/csv",
        )
        try:
            _auto_backup_aktif = bool(st.secrets.get("GITHUB_TOKEN"))
        except Exception:
            _auto_backup_aktif = False
        st.caption(
            "Auto-backup ke GitHub tiap ada transaksi: "
            + ("✅ aktif" if _auto_backup_aktif else "⚙️ belum aktif — set secret `GITHUB_TOKEN` di App settings Streamlit Cloud kalau mau diaktifkan.")
        )
        df_pl = hitung_ringkasan_pl(df_transaksi)

        def warnai_pl(val):
            if isinstance(val, (int, float)) and val != 0:
                return "color: green" if val > 0 else "color: red"
            return ""

        styled_pl = df_pl.style.map(warnai_pl, subset=["P/L Realisasi (Rp)"])
        st.dataframe(styled_pl, use_container_width=True, hide_index=True)

        total_pl = df_pl["P/L Realisasi (Rp)"].sum()
        warna_total = "green" if total_pl > 0 else "red" if total_pl < 0 else "gray"
        st.markdown(f"**Total P/L Realisasi:** :{warna_total}[Rp {total_pl:,.2f}]")

        st.divider()
        st.subheader("Riwayat Transaksi")

        for _, row in df_transaksi.iterrows():
            col_a, col_b = st.columns([6, 1])
            with col_a:
                warna_aksi = "🟢" if row["aksi"] == "Beli" else "🔴"
                st.write(
                    f"{warna_aksi} **{row['tanggal']}** — {row['aksi']} **{row['kode']}** "
                    f"| {row['lot']} lot @ Rp{row['harga']:,.2f} "
                    f"{'| ' + row['alasan'] if row['alasan'] else ''}"
                )
            with col_b:
                if st.button("Hapus", key=f"hapus_{row['id']}"):
                    hapus_transaksi(row["id"])
                    backup_csv_ke_git()  # best-effort, tidak mengganggu kalau gagal/belum dikonfigurasi
                    st.rerun()
