# Quick Start Commands

## 1. Start Backend (Port 9001)
```powershell
# Navigate to project folder
cd C:\Users\eswar\OneDrive\Desktop\Fwd_Simulation

# Activate virtual environment
& .\myenv\Scripts\Activate.ps1

# Start backend with streaming support
uvicorn app.main:app --host 0.0.0.0 --port 9001 --reload
```

**Expected Output:**
```
INFO:     Uvicorn running on http://0.0.0.0:9001 (Press CTRL+C to quit)
INFO:     Started reloader process
INFO:     Started server process
INFO:     Application startup complete.
```

---

## 2. Start Frontend (Port 9000)
**Open a NEW terminal window:**

```powershell
# Navigate to project folder
cd C:\Users\eswar\OneDrive\Desktop\Fwd_Simulation

# Serve frontend
python -m http.server 9000
```

**Expected Output:**
```
Serving HTTP on :: port 9000 (http://[::]:9000/) ...
```

---

## 3. Access Application

### Local Access
```
http://localhost:9000
```

### Network Access (from other machines)
```
http://<your-machine-ip>:9000
```

**Find your IP:**
```powershell
ipconfig | Select-String "IPv4"
```

---

## 4. Test Queries (In Browser)

### Test 1: Simple Query (Streaming)
```
What is the source limit for SRC1?
```

### Test 2: Customer Query (DB + Streaming)
```
Simulate a decision for Alice Johnson sending 3000 USD via SRCX
```

### Test 3: Rule Explanation (Vector Search)
```
Why was rule R002 triggered for the last transaction?
```

### Test 4: Complex Logic (Full Pipeline)
```
Explain the entire decision flow from input to action, including scoring and rule evaluation
```

---

## 5. Test via PowerShell

### Test Non-Streaming Mode
```powershell
$body = @{
    query = "Explain the decision logic"
    stream = $false
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://localhost:9001/query" -Method Post -Body $body -ContentType "application/json"
```

### Test Streaming Mode
```powershell
$body = @{
    query = "What is rule R001?"
    stream = $true
} | ConvertTo-Json

Invoke-WebRequest -Uri "http://localhost:9001/query" -Method Post -Body $body -ContentType "application/json" | Select-Object -ExpandProperty Content
```

---

## 6. Run Automated Tests
```powershell
# Test both streaming and non-streaming modes
python test_streaming.py
```

**Expected Output:**
```
🧪 Testing Streaming Implementation
================================================================================
TEST 0: Health Check
================================================================================
✓ Backend is running!

================================================================================
TEST 1: Non-Streaming Mode
================================================================================
✓ Success!
Model: openrouter:default
Answer length: 542 characters
Code snippets: 3

================================================================================
TEST 2: Streaming Mode (SSE)
================================================================================
✓ Connected to stream!

Receiving chunks:
  [Metadata] Model: openrouter:default, Snippets: 3
  [Chunk 1] 'The '
  [Chunk 2] 'decision '
  [Chunk 3] 'logic '
  
✓ Stream completed!
  Total chunks received: 45
  Response time: 5234.56ms
  Content length: 542 characters

================================================================================
SUMMARY
================================================================================
Non-Streaming        ✓ PASSED
Streaming            ✓ PASSED

✅ All tests passed! Both modes work correctly.
```

---

## 7. Monitor Logs
```powershell
# Watch query analytics in real-time
Get-Content logs\query.log -Wait

# Check application logs
Get-Content logs\app.log -Tail 20

# Search for streaming events
Select-String "Streaming" logs\app.log
```

---

## 8. Health Checks

### Backend Health
```powershell
Invoke-RestMethod -Uri "http://localhost:9001/health"
```

**Expected:** `{"status":"ok"}`

### List Available Models
```powershell
Invoke-RestMethod -Uri "http://localhost:9001/models"
```

**Expected:** Array of model configurations

---

## 9. Stop Services

### Stop Backend
Press `Ctrl+C` in the backend terminal

### Stop Frontend
Press `Ctrl+C` in the frontend terminal

---

## 10. Restart Services (Quick)
```powershell
# In backend terminal (if already activated)
uvicorn app.main:app --host 0.0.0.0 --port 9001 --reload

# In frontend terminal (new window)
python -m http.server 9000
```

---

## Ubuntu/Linux Deployment

### Start Backend
```bash
cd /path/to/Fwd_Simulation
source myenv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 9001 --reload
```

### Start Frontend
```bash
cd /path/to/Fwd_Simulation
python3 -m http.server 9000
```

### Access
```
External: http://<vm-external-ip>:9000
Internal: http://localhost:9000
```

---

## Firewall Configuration (If Needed)

### Windows
```powershell
# Allow port 9000 (frontend)
New-NetFirewallRule -DisplayName "Frontend Port 9000" -Direction Inbound -LocalPort 9000 -Protocol TCP -Action Allow

# Allow port 9001 (backend)
New-NetFirewallRule -DisplayName "Backend Port 9001" -Direction Inbound -LocalPort 9001 -Protocol TCP -Action Allow
```

### Ubuntu
```bash
# Allow port 9000 (frontend)
sudo ufw allow 9000/tcp

# Allow port 9001 (backend)
sudo ufw allow 9001/tcp

# Reload firewall
sudo ufw reload
```

---

## Troubleshooting Commands

### Check if ports are in use
```powershell
# Windows
netstat -ano | findstr "9000"
netstat -ano | findstr "9001"
```

```bash
# Linux
lsof -i :9000
lsof -i :9001
```

### Kill process on port (if needed)
```powershell
# Windows (replace PID with actual process ID from netstat)
taskkill /PID <PID> /F
```

```bash
# Linux
kill -9 $(lsof -t -i:9000)
kill -9 $(lsof -t -i:9001)
```

---

## One-Liner Start (Windows)

```powershell
# Start both services in background
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd C:\Users\eswar\OneDrive\Desktop\Fwd_Simulation; .\myenv\Scripts\Activate.ps1; uvicorn app.main:app --host 0.0.0.0 --port 9001 --reload"

Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd C:\Users\eswar\OneDrive\Desktop\Fwd_Simulation; python -m http.server 9000"
```

Then open browser to `http://localhost:9000`

---

## Summary

✅ **Backend:** Port 9001 (uvicorn with streaming)  
✅ **Frontend:** Port 9000 (Python HTTP server)  
✅ **Access:** `http://localhost:9000` or `http://<machine-ip>:9000`  
✅ **Test:** Use browser or `test_streaming.py`  
✅ **Logs:** `logs/query.log` and `logs/app.log`  

🚀 **Ready to use!**
