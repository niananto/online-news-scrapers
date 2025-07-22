# 🔧 SCHEDULER CONFIGURATION EXPLAINED

## 📊 Basic Scraping Settings

```python
'keyword': 'bangladesh',         # Search term for all outlets
'limit': 1,                     # Max articles per outlet per run
'page_size': 25,                # Articles requested per page
'interval_minutes': 30,         # Run every 30 minutes
```

## 🛡️ Enhanced Scheduler Options (Production-Ready Features)

### **Job Management**
- **`max_instances: 1`** - Only 1 scheduler job can run at a time (prevents overlapping)
- **`coalesce: True`** - If multiple runs are missed, combine them into one execution
- **`misfire_grace_time: 300`** - 5 minutes grace period for delayed job starts

### **Reliability & Error Handling**  
- **`jitter: 10`** - Random 0-10 second delay to prevent all outlets hitting servers simultaneously
- **`max_retries_per_outlet: 2`** - Retry failed outlets up to 2 times before giving up
- **`timeout_per_outlet: 180`** - Each outlet has 3 minutes max to complete scraping

### **Circuit Breaker Protection**
- **`circuit_breaker_threshold: 5`** - After 5 consecutive failures, skip that outlet temporarily
- Prevents wasting resources on consistently failing sources
- Resets to 0 on successful scraping

# 🌐 API ENDPOINTS IN UNIFIED_SERVER.PY

## 📋 Core Endpoints

### **Health & Monitoring**
- **`GET /health`** - Server health check with scheduler status
- **`GET /outlets`** - List all 21 available news outlets  
- **`GET /database/stats`** - Database statistics (total articles, by platform)

### **Scraping Operations**
- **`POST /scrape`** - Original endpoint (scrape only, no database storage)
- **`POST /scrape-and-populate`** - Scrape multiple outlets + save to database

### **Scheduler Management**
- **`GET /scheduler/status`** - Current scheduler status and configuration
- **`POST /scheduler/configure`** - Update scheduler settings
- **`POST /scheduler/trigger`** - Manually trigger scraping job
- **`POST /scheduler/start`** - Start automatic scheduling
- **`POST /scheduler/stop`** - Stop automatic scheduling

## 🔄 Typical Workflow

1. **Start Server:** `python unified_server.py`
2. **Check Status:** `GET /health` 
3. **Manual Trigger:** `POST /scheduler/trigger` (scrapes all 21 outlets)
4. **Monitor Results:** `GET /database/stats`
5. **Configure:** `POST /scheduler/configure` (change intervals, outlets, etc.)

The scheduler automatically runs every 30 minutes, scraping all outlets with built-in error handling, retries, and circuit breaking!