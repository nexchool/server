# How to Find Your Computer's IP Address

## For Physical Device Testing (Expo Go)

When using Expo Go on a **physical device** (real phone), you need to use your computer's local IP address, not `localhost` or `10.0.2.2`.

## Quick Steps

### 1. Find Your IP Address

**macOS:**
```bash
ifconfig | grep "inet " | grep -v 127.0.0.1
```

**Windows:**
```bash
ipconfig
```
Look for "IPv4 Address" under your active network adapter (usually Wi-Fi)

**Linux:**
```bash
hostname -I
```

### 2. Look for an IP like:
- `192.168.1.100`
- `192.168.0.5`
- `10.0.0.5`
- `172.16.0.10`

**Ignore:**
- `127.0.0.1` (this is localhost)
- `169.254.x.x` (this is a self-assigned IP, means you're not connected to Wi-Fi)

### 3. Update the API Configuration

1. Open `client/common/constants/api.ts`
2. Find this line:
   ```typescript
   const PHYSICAL_DEVICE_IP = '192.168.1.100'; // ⬅️ CHANGE THIS
   ```
3. Replace `192.168.1.100` with your actual IP address
4. Save the file
5. Restart your Expo app

### 4. Test the Connection

**On your phone's browser (Chrome/Safari):**
- Go to: `http://YOUR_IP:5001/api`
- Example: `http://192.168.1.100:5001/api`
- You should see: "Hello, World!"

**If it doesn't work:**
- Make sure your phone and computer are on the **same Wi-Fi network**
- Make sure Flask is running: `python app.py`
- Check firewall settings on your computer
- Try restarting both Flask and Expo

## Example

If your IP is `192.168.1.100`, update the file like this:

```typescript
const PHYSICAL_DEVICE_IP = '192.168.1.100'; // Your actual IP
```

Then your app will connect to: `http://192.168.1.100:5001`

