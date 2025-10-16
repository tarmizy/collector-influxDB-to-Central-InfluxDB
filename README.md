# Data Collector

Data Collector untuk mengumpulkan metrics dari multiple InfluxDB source servers (SRV-8 dan SRV-30) dan mengirimkannya ke Central InfluxDB.

## 📁 Struktur Project

```
data-collector/
├── .env                    # Environment variables untuk data collector
├── docker-compose.yaml     # Docker Compose untuk menjalankan data collector
├── Dockerfile             # Docker image untuk data collector
├── requirements.txt       # Python dependencies
├── collector.py           # Main collector script
├── config/
│   └── queries.yaml       # Konfigurasi query untuk berbagai jenis metrics
├── logs/                  # Directory untuk log files
└── README.md              # Dokumentasi ini
```

## 🏗️ Arsitektur Sistem

### 📊 **Overview Arsitektur**

```
┌─────────────────────────────────────────────────────────────────┐
│                    CENTRAL INFLUXDB                             │
│                    (100.120.0.154:8086)                         │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │
│  │ telegraf    │  │power_monitor│  │SRV_monitor  │              │
│  │ bucket      │  │ing bucket   │  │ing bucket   │              │
│  └─────────────┘  └─────────────┘  └─────────────┘              │
└─────────────────────────────────────────────────────────────────┘
         │                    │                    │
         └────────────────────┼────────────────────┘
                              │
         ┌─────────────────────────────────────┐
         │         DATA COLLECTOR              │
         │        (Container/Service)          │
         └─────────────────────────────────────┘
                              │
         ┌─────────────────────────────────────┐
         │       SOURCE SERVERS                │
         ├─────────────────────────────────────┤
         │  ┌─────────────┐  ┌─────────────┐   │
         │  │   SRV-8     │  │   SRV-30    │   │
         │  │ 100.20.30.8 │  │ 100.20.30.30│   │
         │  ├─────────────┤  ├─────────────┤   │
         │  │  telegraf   │  │power_monitor│   │
         │  │   bucket    │  │ing bucket   │   │
         │  │             │  │             │   │
         │  │             │  │SRV_monitor  │   │
         │  │             │  │ing bucket   │   │
         │  └─────────────┘  └─────────────┘   │
         └─────────────────────────────────────┘
```

### 🏢 **Komponen Sistem**

#### **1. Source Servers (SRV-8 & SRV-30)**
- **SRV-8** (`100.20.30.8:8086`): Server utama dengan Telegraf metrics
- **SRV-30** (`100.20.30.30:8086`): Server dengan power monitoring dan SRV monitoring data
- **Organisasi**: SRV-8 menggunakan `default`, SRV-30 menggunakan `SRV`

#### **2. Central InfluxDB**
- **Lokasi**: `100.120.0.154:8086`
- **Organisasi**: `central`
- **Buckets**: 
  - `telegraf` - Menyimpan data sistem dari SRV-8
  - `power_monitoring` - Menyimpan data power dari SRV-30
  - `SRV_monitoring` - Menyimpan data SRV monitoring dari SRV-30

#### **3. Data Collector**
- **Fungsi**: Mengumpulkan data dari source servers dan mengirim ke central
- **Collection Interval**: Setiap 60 detik (configurable)
- **Transformasi**: Standardisasi hostname (`SRV-8` → `SRV_8`, `SRV-30` → `SRV_30`)

### 🌐 **Network Architecture**

```
Internet/External Network
        │
        ▼
┌─────────────────────────────────────────────────────────┐
│                LOCAL NETWORK                            │
├─────────────────────────────────────────────────────────┤
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐  │
│  │   SRV-8     │    │   SRV-30    │    │   CENTRAL   │  │
│  │ 100.20.30.8 │    │100.20.30.30 │    │100.120.0.154│  │
│  │ :8086       │    │ :8086       │    │ :8086       │  │
│  └─────────────┘    └─────────────┘    └─────────────┘  │
└─────────────────────────────────────────────────────────┘
         │                    │                    │
         └────────────────────┼────────────────────┘
                              │
         ┌─────────────────────────────────────┐
         │         DATA COLLECTOR              │
         │       (Same Network)                │
         └─────────────────────────────────────┘
```

### 🔄 **Data Flow**

#### **1. Data Collection Process**
```
Source Server → Data Collector → Central InfluxDB
     │                │                │
     ▼                ▼                ▼
1. Query data     2. Transform      3. Write to
   dari source      hostname &        target bucket
   servers          structure
```

#### **2. Detailed Data Flow**

**Step 1: Query Source Servers**
```bash
# Query dari SRV-8 (telegraf bucket)
from(bucket: "telegraf") |> range(start: -5m) |> filter(fn: (r) => r._measurement == "cpu")

# Query dari SRV-30 (power_monitoring bucket)  
from(bucket: "power_monitoring") |> range(start: -5m) |> filter(fn: (r) => r._field != "chair_section")
```

**Step 2: Data Transformation**
```bash
# Transformasi hostname
Original: "SRV-8" → Standardized: "SRV_8"
Original: "SRV-30" → Standardized: "SRV_30"

# Penambahan metadata
Tags: host, source_bucket, field
Buckets: telegraf → telegraf, power_monitoring → power_monitoring
```

**Step 3: Write to Central InfluxDB**
```bash
# Write ke bucket yang sesuai
Write to: telegraf bucket (dari SRV-8)
Write to: power_monitoring bucket (dari SRV-30)
Write to: SRV_monitoring bucket (dari SRV-30)
```

### 🚀 **Deployment Architecture**

#### **Option 1: Docker Compose (Recommended)**
```bash
# Central InfluxDB
central-influxdb/
├── docker-compose.yml     # Central InfluxDB container
└── .env                   # Central configuration

# Data Collector  
data-collector/
├── docker-compose.yml     # Data collector container
├── .env                   # Collector configuration
└── collector.py          # Application code
```

#### **Option 2: Manual Deployment**
```bash
# Install dependencies
pip3 install -r requirements.txt

# Run collector
python3 collector.py

# Access logs
tail -f logs/collector.log

# Health check
curl http://localhost:5000/health
```

### 📈 **Monitoring & Observability**

#### **Health Endpoints**
- **Data Collector Health**: `http://localhost:5000/health`
- **Central InfluxDB Health**: `http://100.120.0.154:8086/health`

#### **Metrics Collection**
- **Total Metrics**: Auto-tracked dalam collector logs
- **Success Rate**: Tracked per source server
- **Data Points**: Counted per collection cycle

#### **Log Locations**
- **Collector Logs**: `./logs/collector.log`
- **Central InfluxDB Logs**: Container logs atau `/var/log/influxdb/`

### 🔧 **Configuration Management**

#### **Environment Variables Hierarchy**
1. **Central InfluxDB** (`.env` di root project)
   - Database connection settings
   - Admin credentials

2. **Data Collector** (`.env` di data-collector folder)
   - Source server connections
   - Collection intervals
   - Query configurations

#### **Query Templates**
- **System Metrics**: CPU, Memory, Disk, Network
- **Power Monitoring**: Current measurements dengan filtering
- **SRV Monitoring**: Kubernetes/container metrics

### 🛡️ **Security Considerations**

#### **Authentication**
- **Token-based**: Setiap server menggunakan token unik
- **Organization-based**: Setiap server memiliki organisasi terpisah
- **Network Security**: Internal network communication

#### **Data Protection**
- **Encrypted Tokens**: Tokens disimpan sebagai environment variables
- **Access Control**: Organization-level permissions
- **Audit Trail**: Complete logging untuk semua operasi

### 📊 **Performance Characteristics**

#### **Collection Performance**
- **Interval**: 60 detik (configurable)
- **Batch Size**: ~500-1000 points per cycle
- **Throughput**: Depends on source server performance

#### **Resource Usage**
- **Memory**: ~50-100MB untuk collector process
- **CPU**: Minimal (mostly I/O bound)
- **Network**: Low bandwidth (metrics data)

### 🔍 **Troubleshooting Architecture**

#### **Debugging Flow**
1. **Check Logs**: `logs/collector.log` untuk error messages
2. **Verify Connections**: Test koneksi ke semua servers
3. **Validate Data**: Query central InfluxDB untuk memastikan data masuk
4. **Check Queries**: Pastikan query syntax benar untuk setiap bucket

#### **Common Issues**
- **Connection Failures**: Network atau authentication issues
- **Query Errors**: Incompatible data types atau bucket structures
- **Write Failures**: Permission atau bucket configuration issues

## 📁 Struktur Project

```
data-collector/
├── .env                    # Environment variables untuk data collector
├── docker-compose.yaml     # Docker Compose untuk menjalankan data collector
├── Dockerfile             # Docker image untuk data collector
├── requirements.txt       # Python dependencies
├── collector.py           # Main collector script
├── config/
│   └── queries.yaml       # Konfigurasi query untuk berbagai jenis metrics
├── logs/                  # Directory untuk log files
└── README.md              # Dokumentasi ini
```

## 🚀 Cara Menjalankan

### Menggunakan Docker Compose (Recommended)

```bash
# Build dan jalankan data collector
docker-compose up -d

# Lihat logs
docker-compose logs -f data-collector

# Stop data collector
docker-compose down
```

### Menjalankan Langsung dengan Python

```bash
# Install dependencies
pip3 install -r requirements.txt

# Jalankan collector
python3 collector.py
```

## ⚙️ Konfigurasi

### Environment Variables (.env)

```bash
# Central InfluxDB (tujuan pengiriman data)
INFLUXDB_CENTRAL_URL=http://100.120.0.154:8086
INFLUXDB_CENTRAL_TOKEN=central_token_abcdef123456
INFLUXDB_CENTRAL_ORG=central
INFLUXDB_CENTRAL_BUCKET=metrics

# Source Server A (SRV-8)
SERVER_A_URL=http://100.20.30.8:8086
SERVER_A_TOKEN=z7qh_aJzI1RIfmNvCD9djvZpE6_0QtlDzJkSXNPbfyB9s6Ftowtk3hISOYky3GI0YotmP1Clx7OgGrD7ONLabw==
SERVER_A_ORG=default
SERVER_A_BUCKET=telegraf

# Source Server B (SRV-30)
SERVER_B_URL=http://100.20.30.30:8086
SERVER_B_TOKEN=wb9iiVQfgJDSq1o6YnbOjuTeehUOAe8-gFWXRBDeG9kVvlegMcDyU3NOIjEXVT9PcoR9ispIBe8whbXrVcGcTA==
SERVER_B_ORG=SRV
SERVER_B_BUCKET=SRV_monitoring
SERVER_B_BUCKET_2=power_monitoring

# Data Collector Settings
COLLECTOR_INTERVAL=60
HEALTH_CHECK_PORT=5000
LOG_LEVEL=INFO
```

### Query Configuration (config/queries.yaml)

Konfigurasi query untuk berbagai jenis metrics yang akan dikumpulkan dari source servers.

## 📊 Fitur

### ✅ Bucket Mapping
- Data dari `telegraf` bucket → `telegraf` bucket di central
- Data dari `power_monitoring` bucket → `power_monitoring` bucket di central
- Data dari `SRV_monitoring` bucket → `SRV_monitoring` bucket di central

### ✅ Hostname Standardization
- `SRV-8` → `SRV_8`
- `SRV-30` → `SRV_30`

### ✅ Host-based Filtering
Data dapat difilter berdasarkan:
- `host`: SRV_8, SRV_30
- `source_bucket`: telegraf, power_monitoring, SRV_monitoring

### ✅ Real-time Collection
- Mengumpulkan data setiap 60 detik (configurable)
- Health check endpoint di `http://localhost:5000/health`
- Detailed logging di `logs/collector.log`

## 🔍 Monitoring & Troubleshooting

### Cek Status Collection
```bash
# Via HTTP endpoint
curl http://localhost:5000/health

# Via logs
tail -f logs/collector.log
```

### Cek Data di Central InfluxDB
```bash
# Lihat measurements dari SRV-8
curl -s "http://100.120.0.154:8086/api/v2/query?org=central" \
  -H "Authorization: Token central_token_abcdef123456" \
  -H "Content-Type: application/vnd.flux" \
  -d 'from(bucket: "telegraf") |> range(start: -1h) |> filter(fn: (r) => r.host == "SRV_8") |> count()'

# Lihat measurements dari SRV-30
curl -s "http://100.120.0.154:8086/api/v2/query?org=central" \
  -H "Authorization: Token central_token_abcdef123456" \
  -H "Content-Type: application/vnd.flux" \
  -d 'from(bucket: "power_monitoring") |> range(start: -1h) |> filter(fn: (r) => r.host == "SRV_30") |> count()'
```

## 🐛 Troubleshooting

### Error: "unsupported aggregate column type string"
- Terjadi ketika query mencoba mengaggregate field string dengan function `mean`
- Solusi: Query sudah difilter untuk exclude string fields

### Error: Connection refused
- Pastikan Central InfluxDB running di `http://100.120.0.154:8086`
- Cek token dan organization name

### Error: No data collected
- Cek logs untuk error messages
- Pastikan source servers dapat diakses
- Verifikasi konfigurasi di `.env` file

## 📝 Logs

Logs tersimpan di:
- Container: `/app/logs/collector.log`
- Host: `./logs/collector.log` (jika menggunakan volume mount)

Log levels dapat diatur melalui `LOG_LEVEL` di `.env` file.