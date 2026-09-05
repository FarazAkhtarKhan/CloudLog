# CloudLog Operations Dashboard

A modern, responsive web dashboard built with **React 19** and **Vite** for monitoring cloud microservices, reviewing operational telemetry, and responding to critical incidents in real time.

---

## What Does the Dashboard Do?

1. **System Health Metrics**: Displays live counters for total ingested logs, critical errors, application errors, and open incidents.
2. **Incident Response Queue**: Displays all detected system incidents. Responders can view root-cause messages, inspect affected services, and mark resolved incidents.
3. **Live Telemetry Stream**: Shows application logs flowing through the system with filtering by service name and severity level (`INFO`, `WARNING`, `ERROR`, `CRITICAL`).
4. **Live Incident Simulator**: Allows testers and examiners to trigger real incident scenarios with one click (e.g. database deadlocks, payment timeouts) directly in AWS without using the terminal.
5. **Role-Based Access Control (RBAC)**: Enforces permissions based on AWS Cognito user groups:
   - **Admin / Analyst**: Can view telemetry and resolve incidents.
   - **Viewer**: Read-only access (resolving incidents is blocked).

---

## Tech Stack

- **Framework**: React 19 + Vite
- **Styling**: Clean Vanilla CSS with dark mode and glassmorphism (no bulky UI frameworks)
- **Icons**: Lucide React
- **Authentication**: AWS Cognito User Pools (Direct JWT via `USER_PASSWORD_AUTH`)
- **API Client**: Native `fetch` with automatic bearer token attachment

---

## Demo Accounts

The login page provides one-click buttons to sign in with pre-configured accounts:

| Role | Email | Password | Permissions |
| :--- | :--- | :--- | :--- |
| **Admin** | `admin@cloudlog.local` | `CloudLogAdmin#2026` | Full access (view and resolve incidents) |
| **Analyst** | `analyst@cloudlog.local` | `CloudLogAnalyst#2026` | Operational access (view and resolve incidents) |
| **Viewer** | `viewer@cloudlog.local` | `CloudLogViewer#2026` | Read-only access (cannot resolve incidents) |

---

## How to Run Locally

### 1. Install Dependencies
```bash
npm install
```

### 2. Start the Development Server
```bash
npm run dev
```
Open [http://localhost:5173](http://localhost:5173) in your browser.

### 3. Build for Production
```bash
npm run build
```
The optimized static bundle will be output to the `dist/` directory.

