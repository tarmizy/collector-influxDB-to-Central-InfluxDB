# data-collector/collector.py
import os
import time
import logging
import yaml
from datetime import datetime, timedelta, timezone
from influxdb_client import InfluxDBClient
from influxdb_client.client.exceptions import InfluxDBError
from flask import Flask, jsonify
import schedule
import threading

# Load .env file
def load_env_file():
    """Load environment variables from .env file"""
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key] = value

# Load .env file before importing other modules that might need env vars
load_env_file()

# Setup logging
log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

# Create logs directory if it doesn't exist
log_dir = 'logs'
os.makedirs(log_dir, exist_ok=True)

logging.basicConfig(
    level=os.getenv('LOG_LEVEL', 'INFO'),
    format=log_format,
    handlers=[
        logging.FileHandler(os.path.join(log_dir, 'collector.log')),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

class CentralDataCollector:
    def __init__(self):
        self.load_config()
        self.setup_clients()
        self.load_queries()
        self.metrics_collected = 0
        self.last_collection = None
        self.collection_stats = {
            'server_a': {'success': 0, 'failed': 0, 'last_points': 0, 'last_hosts': []},
            'server_b': {'success': 0, 'failed': 0, 'last_points': 0, 'last_hosts': []}
        }
        
    def load_config(self):
        """Load configuration from environment"""
        self.central_config = {
            'url': os.getenv('INFLUXDB_CENTRAL_URL'),
            'token': os.getenv('INFLUXDB_CENTRAL_TOKEN'),
            'org': os.getenv('INFLUXDB_CENTRAL_ORG'),
            'bucket': os.getenv('INFLUXDB_CENTRAL_BUCKET')
        }
        
        self.sources = {
            'server_a': {
                'url': os.getenv('SERVER_A_URL'),
                'token': os.getenv('SERVER_A_TOKEN'),
                'org': os.getenv('SERVER_A_ORG'),
                'buckets': [os.getenv('SERVER_A_BUCKET')],  # Single bucket
                'enabled': True,
                'last_success': None
            },
            'server_b': {
                'url': os.getenv('SERVER_B_URL'),
                'token': os.getenv('SERVER_B_TOKEN'),
                'org': os.getenv('SERVER_B_ORG'),
                'buckets': [
                    os.getenv('SERVER_B_BUCKET'),        # pod_monitoring
                    os.getenv('SERVER_B_BUCKET_2')       # power_monitoring
                ],
                'enabled': True,
                'last_success': None
            }
        }
        
        self.interval = int(os.getenv('COLLECTOR_INTERVAL', 60))
        self.health_port = int(os.getenv('HEALTH_CHECK_PORT', 5000))
        
    def setup_clients(self):
        """Setup InfluxDB clients"""
        try:
            # Central client
            self.central_client = InfluxDBClient(
                url=self.central_config['url'],
                token=self.central_config['token'],
                org=self.central_config['org']
            )
            self.central_write_api = self.central_client.write_api()
            logger.info("✅ Central InfluxDB client configured")
        except Exception as e:
            logger.error(f"❌ Failed to configure central client: {e}")
            raise
        
        # Source clients
        self.source_clients = {}
        for name, config in self.sources.items():
            if config['enabled']:
                try:
                    self.source_clients[name] = InfluxDBClient(
                        url=config['url'],
                        token=config['token'],
                        org=config['org']
                    )
                    logger.info(f"✅ Client configured for {name} with {len(config['buckets'])} buckets")
                except Exception as e:
                    logger.error(f"❌ Failed to configure client for {name}: {e}")
                    self.sources[name]['enabled'] = False
    
    def load_queries(self):
        """Load Flux queries from YAML configuration"""
        try:
            config_path = os.path.join(os.path.dirname(__file__), 'config', 'queries.yaml')
            with open(config_path, 'r') as f:
                self.queries = yaml.safe_load(f)
            logger.info("✅ Query configuration loaded")
        except Exception as e:
            logger.error(f"❌ Failed to load query configuration: {e}")
            # Fallback to default queries - SESUAI DENGAN YAML TERBARU
            self.queries = {
                'queries': {
                    'system_metrics': {
                        'flux_query': '''from(bucket: "{{ bucket }}")
  |> range(start: -{{ minutes }}m)
  |> filter(fn: (r) => 
    r._measurement == "cpu" or 
    r._measurement == "mem" or 
    r._measurement == "disk" or
    r._measurement == "system"
  )
  |> group(columns: ["host", "_measurement", "_field"])
  |> aggregateWindow(every: 1m, fn: mean, createEmpty: false)''',
                        'minutes': 5
                    },
                    'network_metrics': {
                        'flux_query': '''from(bucket: "{{ bucket }}")
  |> range(start: -{{ minutes }}m)
  |> filter(fn: (r) => r._measurement == "net")
  |> group(columns: ["host", "_measurement", "_field"])
  |> aggregateWindow(every: 1m, fn: mean, createEmpty: false)''',
                        'minutes': 5
                    },
                    'pod_monitoring': {
                        'flux_query': '''from(bucket: "{{ bucket }}")
  |> range(start: -{{ minutes }}m)
  |> group(columns: ["_measurement", "_field", "host"])
  |> aggregateWindow(every: 1m, fn: mean, createEmpty: false)''',
                        'minutes': 5
                    },
                    'power_monitoring': {
                        'flux_query': '''from(bucket: "{{ bucket }}")
  |> range(start: -{{ minutes }}m)
  |> group(columns: ["_measurement", "_field", "host"])
  |> aggregateWindow(every: 1m, fn: mean, createEmpty: false)''',
                        'minutes': 5
                    }
                }
            }
    
    def override_hostname(self, server_name, original_hostname):
        """Override hostname based on server and standardize naming"""
        # Standardized hostname mapping
        hostname_mapping = {
            'server_a': 'pod_8',
            'server_b': 'pod_30'
        }

        # Jika hostname unknown atau kosong, gunakan mapping berdasarkan server
        if original_hostname == 'unknown' or not original_hostname:
            return hostname_mapping.get(server_name, f"unknown_{server_name}")

        # Untuk server tertentu, override dengan mapping standar
        if server_name in hostname_mapping:
            return hostname_mapping[server_name]

        return original_hostname.lower().replace('-', '_')
    
    def test_connections(self):
        """Test connection to all servers"""
        logger.info("🔌 Testing connections to source servers...")
        
        results = {'central': False, 'sources': {}}
        
        # Test central connection
        try:
            health = self.central_client.health()
            if health.status == "pass":
                logger.info("✅ Central InfluxDB: Healthy")
                results['central'] = True
            else:
                logger.error(f"❌ Central InfluxDB: Unhealthy - {health.message}")
        except Exception as e:
            logger.error(f"❌ Central InfluxDB: Connection failed - {e}")
        
        # Test source connections
        for server_name, client in self.source_clients.items():
            try:
                health = client.health()
                if health.status == "pass":
                    # Test each bucket
                    bucket_status = []
                    for bucket in self.sources[server_name]['buckets']:
                        try:
                            test_query = f'from(bucket: "{bucket}") |> range(start: -1m) |> limit(n: 1)'
                            client.query_api().query(test_query)
                            bucket_status.append(f"✅ {bucket}")
                        except Exception as e:
                            bucket_status.append(f"❌ {bucket}: {str(e)}")
                    
                    logger.info(f"✅ {server_name}: Healthy - Buckets: {', '.join(bucket_status)}")
                    results['sources'][server_name] = True
                    self.sources[server_name]['enabled'] = True
                else:
                    logger.error(f"❌ {server_name}: Unhealthy - {health.message}")
                    results['sources'][server_name] = False
                    self.sources[server_name]['enabled'] = False
            except Exception as e:
                logger.error(f"❌ {server_name}: Connection failed - {e}")
                results['sources'][server_name] = False
                self.sources[server_name]['enabled'] = False
        
        return results
    
    def execute_query(self, server_name, bucket_name, query_name):
        """Execute a specific query against a source server and bucket"""
        if not self.sources[server_name]['enabled']:
            return []
            
        try:
            query_config = self.queries['queries'].get(query_name)
            if not query_config:
                logger.warning(f"Query {query_name} not found in configuration")
                return []
            
            # Render query template
            flux_query = query_config['flux_query'].replace(
                '{{ bucket }}', bucket_name
            ).replace(
                '{{ minutes }}', str(query_config.get('minutes', 5))
            )
            
            client = self.source_clients[server_name]
            query_api = client.query_api()
            
            logger.debug(f"Executing {query_name} for {server_name} bucket {bucket_name}")
            result = query_api.query(flux_query)
            
            return result
            
        except Exception as e:
            logger.error(f"❌ bucket {bucket_name} query {query_name} failed: {e}")
            return []
    
    def transform_data(self, result, server_name, bucket_name):
        """Transform query result to central format with hostname override"""
        points = []
        original_hosts = set()
        final_hosts = set()
        
        for table in result:
            for record in table.records:
                # Get original hostname
                original_host = record.values.get('host', 'unknown')
                original_hosts.add(original_host)
                
                # Override hostname
                final_host = self.override_hostname(server_name, original_host)
                final_hosts.add(final_host)
                
                # Build tags - fokus pada host untuk filtering, tanpa nama server
                tags = {
                    "host": final_host,  # Hostname yang sudah di-standarisasi
                    "source_bucket": bucket_name,  # Track which bucket data came from
                    "field": record.get_field(),
                }
                
                # Add additional tags (excluding internal fields)
                for key, value in record.values.items():
                    if key not in ['result', 'table', '_start', '_stop', '_time', '_value', '_field', '_measurement', 'host']:
                        if value is not None:
                            tags[key] = str(value)
                
                point = {
                    "measurement": f"{record.get_measurement()}",  # Simplified measurement name without server prefix
                    "tags": tags,
                    "fields": {
                        "value": float(record.get_value()) if record.get_value() is not None else 0.0
                    },
                    "time": record.get_time()
                }
                points.append(point)
        
        if points:
            logger.info(f"🔧 Transformed {len(points)} points from {bucket_name}. Host mapping: {original_hosts} → {final_hosts}")
        
        return points
    
    def collect_from_source(self, server_name):
        """Collect data from a single source server - multiple buckets"""
        if not self.sources[server_name]['enabled']:
            return 0
            
        total_points = 0
        unique_hosts = set()
        bucket_points = {}
        
        try:
            # Collect from each bucket
            for bucket_name in self.sources[server_name]['buckets']:
                if not bucket_name:  # Skip empty bucket names
                    continue
                    
                bucket_total = 0
                logger.info(f"📦 Collecting from bucket: {bucket_name}")
                
                # Execute ALL queries for each bucket (no filtering)
                for query_name in self.queries['queries'].keys():
                    try:
                        result = self.execute_query(server_name, bucket_name, query_name)
                        
                        if result:
                            points = self.transform_data(result, server_name, bucket_name)
                            
                            # Track unique hosts
                            for point in points:
                                if 'host' in point['tags']:
                                    unique_hosts.add(point['tags']['host'])
                            
                            # Write to central InfluxDB - Use source bucket name as central bucket
                            if points:
                                # Use source bucket name as central bucket name for better organization
                                central_bucket = bucket_name
                                try:
                                    self.central_write_api.write(
                                        bucket=central_bucket,
                                        record=points
                                    )
                                    bucket_total += len(points)
                                    total_points += len(points)
                                    logger.debug(f"📊 {len(points)} points written to {central_bucket}")
                                except Exception as e:
                                    logger.error(f"❌ Failed to write {len(points)} points to {central_bucket}: {e}")
                                    continue
                                
                    except Exception as e:
                        logger.error(f"❌ Query {query_name} failed for bucket {bucket_name}: {e}")
                        continue
                
                bucket_points[bucket_name] = bucket_total
            
            if total_points > 0:
                hosts_list = ", ".join(sorted(unique_hosts)) if unique_hosts else "unknown"
                bucket_summary = ", ".join([f"{k}: {v}" for k, v in bucket_points.items()])
                logger.info(f"✅ Collected {total_points} metrics from buckets [{bucket_summary}] → hosts: {hosts_list}")
                self.collection_stats[server_name]['success'] += 1
                self.collection_stats[server_name]['last_points'] = total_points
                self.collection_stats[server_name]['last_hosts'] = list(unique_hosts)
                self.collection_stats[server_name]['last_buckets'] = bucket_points
                self.sources[server_name]['last_success'] = datetime.now(timezone.utc)
            else:
                logger.warning(f"⚠️ No data collected from any bucket")
                
            return total_points
                
        except Exception as e:
            logger.error(f"❌ {server_name}: Collection failed - {e}")
            self.collection_stats[server_name]['failed'] += 1
            self.sources[server_name]['enabled'] = False
            return 0
    
    def collect_all_sources(self):
        """Collect data from all enabled source servers"""
        total_points = 0
        logger.info("🔄 Starting data collection cycle...")
        
        for server_name in self.source_clients.keys():
            points_collected = self.collect_from_source(server_name)
            total_points += points_collected
            self.metrics_collected += points_collected
        
        self.last_collection = datetime.now(timezone.utc)
        logger.info(f"✅ Collection complete: {total_points} points collected")
        return total_points
    
    def get_status(self):
        """Get collector status for health endpoint"""
        status = {
            'status': 'healthy',
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'metrics_collected_total': self.metrics_collected,
            'last_collection': self.last_collection.isoformat() if self.last_collection else None,
            'collection_interval': self.interval,
            'sources': {}
        }
        
        for server_name, config in self.sources.items():
            status['sources'][server_name] = {
                'enabled': config['enabled'],
                'buckets': config['buckets'],
                'last_success': config['last_success'].isoformat() if config['last_success'] else None,
                'stats': self.collection_stats[server_name]
            }
            
            # If any source is disabled, mark status as degraded
            if not config['enabled']:
                status['status'] = 'degraded'
        
        return status
    
    def run_continuous(self):
        """Run continuous collection"""
        logger.info(f"🚀 Starting continuous collection every {self.interval} seconds")
        
        # Initial connection test
        connection_results = self.test_connections()
        enabled_servers = [k for k, v in self.sources.items() if v['enabled']]
        logger.info(f"📡 Monitoring {len(enabled_servers)} data sources")
        
        # Schedule collection
        schedule.every(self.interval).seconds.do(self.collect_all_sources)
        
        # Run immediately first time
        self.collect_all_sources()
        
        # Main loop
        while True:
            try:
                schedule.run_pending()
                time.sleep(1)
                
                # Re-test connections every hour
                if self.metrics_collected % (3600 // self.interval) == 0:
                    self.test_connections()
                    
            except KeyboardInterrupt:
                logger.info("⏹️ Collection stopped by user")
                break
            except Exception as e:
                logger.error(f"💥 Unexpected error: {e}")
                time.sleep(30)

# Flask routes for health checks
collector_instance = None

@app.route('/health')
def health():
    if collector_instance:
        return jsonify(collector_instance.get_status())
    else:
        return jsonify({'status': 'initializing'}), 503

@app.route('/metrics')
def metrics():
    """Simple metrics endpoint"""
    if collector_instance:
        status = collector_instance.get_status()
        return jsonify({
            'metrics_collected_total': status['metrics_collected_total'],
            'sources_count': len(status['sources']),
            'enabled_sources': len([s for s in status['sources'].values() if s['enabled']])
        })
    else:
        return jsonify({'error': 'Collector not initialized'}), 503

def start_flask_app():
    """Start Flask app in a separate thread"""
    app.run(host='0.0.0.0', port=collector_instance.health_port, debug=False)

if __name__ == "__main__":
    # Initialize collector
    collector_instance = CentralDataCollector()
    
    # Start health check API in background thread
    flask_thread = threading.Thread(target=start_flask_app, daemon=True)
    flask_thread.start()
    
    # Start data collection
    collector_instance.run_continuous()