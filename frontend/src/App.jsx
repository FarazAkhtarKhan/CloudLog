import React, { useState, useEffect, useCallback } from "react";
import {
  ShieldAlert,
  AlertTriangle,
  Flame,
  CheckCircle2,
  Database,
  RefreshCw,
  LogOut,
  User,
  Radio,
  X,
  Clock,
  KeyRound,
  Filter,
  FileText,
  Server,
  Activity,
  Check,
  AlertCircle,
  Zap,
  Send,
} from "lucide-react";
import { login, logout, getCurrentUser } from "./services/auth";
import {
  getStatistics,
  getServices,
  getEvents,
  getIncidents,
  resolveIncident,
  simulateLog,
} from "./services/api";
import { DEMO_ACCOUNTS } from "./config";
import "./App.css";

export default function App() {
  const [currentUser, setCurrentUser] = useState(() => getCurrentUser());
  const [authEmail, setAuthEmail] = useState("");
  const [authPassword, setAuthPassword] = useState("");
  const [authLoading, setAuthLoading] = useState(false);
  const [authError, setAuthError] = useState(null);

  // Dashboard Data State
  const [stats, setStats] = useState(null);
  const [services, setServices] = useState([]);
  const [incidents, setIncidents] = useState([]);
  const [events, setEvents] = useState([]);
  const [selectedIncident, setSelectedIncident] = useState(null);

  // Filters & Controls
  const [incidentTab, setIncidentTab] = useState("ALL"); // ALL, OPEN, RESOLVED
  const [filterService, setFilterService] = useState("");
  const [filterLevel, setFilterLevel] = useState("");
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [actionError, setActionError] = useState(null);
  const [actionSuccess, setActionSuccess] = useState(null);
  const [resolvingId, setResolvingId] = useState(null);

  // In-Dashboard Incident / Log Simulator State
  const [showSimModal, setShowSimModal] = useState(false);
  const [simService, setSimService] = useState("database-cluster");
  const [simLevel, setSimLevel] = useState("CRITICAL");
  const [simMessage, setSimMessage] = useState("Database deadlock detected on write replica during checkout commit");
  const [simErrorCode, setSimErrorCode] = useState("CRIT_DB_DEADLOCK");
  const [simulating, setSimulating] = useState(false);

  // Handle Login
  const handleLogin = async (email, password) => {
    setAuthLoading(true);
    setAuthError(null);
    try {
      const user = await login(email, password);
      setCurrentUser(user);
    } catch (err) {
      setAuthError(err.message || "Failed to authenticate with AWS Cognito");
    } finally {
      setAuthLoading(false);
    }
  };

  const handleLogout = () => {
    logout();
    setCurrentUser(null);
    setStats(null);
    setIncidents([]);
    setEvents([]);
    setSelectedIncident(null);
  };

  // Fetch Dashboard Data
  const loadDashboardData = useCallback(async (quiet = false) => {
    if (!currentUser) return;
    if (!quiet) setIsRefreshing(true);
    try {
      const [statsRes, servicesRes, incidentsRes, eventsRes] = await Promise.all([
        getStatistics().catch((e) => {
          console.error("Failed to load statistics:", e);
          return null;
        }),
        getServices().catch((e) => {
          console.error("Failed to load services:", e);
          return [];
        }),
        getIncidents({
          status: incidentTab === "ALL" ? undefined : incidentTab,
        }).catch((e) => {
          console.error("Failed to load incidents:", e);
          return [];
        }),
        getEvents({
          service: filterService || undefined,
          level: filterLevel || undefined,
          limit: 30,
        }).catch((e) => {
          console.error("Failed to load events:", e);
          return [];
        }),
      ]);

      if (statsRes) setStats(statsRes);
      if (servicesRes) setServices(servicesRes);
      if (incidentsRes) setIncidents(incidentsRes);
      if (eventsRes) setEvents(eventsRes);
    } catch (err) {
      console.error("Dashboard refresh error:", err);
    } finally {
      if (!quiet) setIsRefreshing(false);
    }
  }, [currentUser, incidentTab, filterService, filterLevel]);

  // Initial load and filter change trigger
  useEffect(() => {
    if (currentUser) {
      loadDashboardData();
    }
  }, [currentUser, incidentTab, filterService, filterLevel, loadDashboardData]);

  // Auto-refresh interval (10 seconds)
  useEffect(() => {
    if (!currentUser || !autoRefresh) return;
    const interval = setInterval(() => {
      loadDashboardData(true);
    }, 10000);
    return () => clearInterval(interval);
  }, [currentUser, autoRefresh, loadDashboardData]);

  // Handle Resolve Incident
  const handleResolve = async (incidentId) => {
    if (currentUser?.role === "Viewer") {
      setActionError("Viewer role is read-only. Analysts or Admins can resolve incidents.");
      return;
    }
    setResolvingId(incidentId);
    setActionError(null);
    setActionSuccess(null);
    try {
      await resolveIncident(incidentId);
      setActionSuccess(`Incident ${incidentId.slice(0, 8)}... resolved successfully.`);
      // Reload incidents and statistics
      await loadDashboardData(true);
      if (selectedIncident && selectedIncident.incident_id === incidentId) {
        setSelectedIncident((prev) => ({
          ...prev,
          status: "RESOLVED",
          resolved_by: currentUser.email,
          resolved_at: new Date().toISOString(),
        }));
      }
    } catch (err) {
      setActionError(err.message || "Failed to resolve incident");
    } finally {
      setResolvingId(null);
    }
  };

  // Handle Simulation
  const handleSimulateSubmit = async (e) => {
    if (e) e.preventDefault();
    if (currentUser?.role === "Viewer") {
      setActionError("Viewer role is read-only. Switch to Analyst or Admin to simulate logs.");
      return;
    }
    setSimulating(true);
    setActionError(null);
    setActionSuccess(null);
    try {
      const res = await simulateLog({
        service: simService,
        level: simLevel,
        message: simMessage,
        error_code: simErrorCode || undefined,
      });
      setShowSimModal(false);
      setActionSuccess(`🚀 Event simulated! Uploaded to S3: ${res.s3_key || "raw-logs/simulations/"}. Lambda is analyzing it now...`);
      // Trigger delayed refreshes to allow Lambda -> DynamoDB async pipeline to finish
      setTimeout(() => loadDashboardData(true), 1200);
      setTimeout(() => loadDashboardData(true), 3500);
    } catch (err) {
      setActionError(err.message || "Failed to simulate log event");
    } finally {
      setSimulating(false);
    }
  };

  // -------------------------------------------------------------
  // RENDER: LOGIN SCREEN
  // -------------------------------------------------------------
  if (!currentUser) {
    return (
      <div className="auth-wrapper">
        <div className="auth-card">
          <div className="auth-header">
            <div style={{ display: "inline-flex", padding: "0.75rem", background: "linear-gradient(135deg, #3b82f6, #8b5cf6)", borderRadius: "12px", marginBottom: "1rem", boxShadow: "0 0 20px rgba(99,102,241,0.4)" }}>
              <ShieldAlert size={36} color="#ffffff" />
            </div>
            <h1 style={{ fontSize: "1.6rem", fontWeight: "700", letterSpacing: "-0.02em" }}>CloudLog</h1>
            <p style={{ color: "var(--text-muted)", fontSize: "0.85rem", marginTop: "0.25rem" }}>
              Serverless Critical Log Analysis & Incident Detection
            </p>
          </div>

          {authError && (
            <div style={{ padding: "0.75rem 1rem", background: "rgba(239, 68, 68, 0.15)", border: "1px solid rgba(239, 68, 68, 0.4)", borderRadius: "8px", color: "#f87171", fontSize: "0.85rem", marginBottom: "1.25rem", display: "flex", alignItems: "center", gap: "0.5rem" }}>
              <AlertCircle size={16} />
              <span>{authError}</span>
            </div>
          )}

          <form
            onSubmit={(e) => {
              e.preventDefault();
              handleLogin(authEmail, authPassword);
            }}
            style={{ display: "flex", flexDirection: "column", gap: "1rem" }}
          >
            <div>
              <label style={{ display: "block", fontSize: "0.75rem", fontWeight: "600", textTransform: "uppercase", color: "var(--text-secondary)", marginBottom: "0.35rem" }}>
                Email Address
              </label>
              <input
                type="email"
                required
                value={authEmail}
                onChange={(e) => setAuthEmail(e.target.value)}
                placeholder="user@cloudlog.local"
                style={{ width: "100%" }}
              />
            </div>

            <div>
              <label style={{ display: "block", fontSize: "0.75rem", fontWeight: "600", textTransform: "uppercase", color: "var(--text-secondary)", marginBottom: "0.35rem" }}>
                Password
              </label>
              <input
                type="password"
                required
                value={authPassword}
                onChange={(e) => setAuthPassword(e.target.value)}
                placeholder="••••••••••••"
                style={{ width: "100%" }}
              />
            </div>

            <button
              type="submit"
              className="btn btn-primary"
              disabled={authLoading}
              style={{ width: "100%", padding: "0.75rem", marginTop: "0.5rem" }}
            >
              {authLoading ? (
                <>
                  <RefreshCw size={16} className="spinning" /> Authenticating...
                </>
              ) : (
                <>
                  <KeyRound size={16} /> Sign In
                </>
              )}
            </button>
          </form>

          {/* Rapid Demo Login Options */}
          <div className="demo-account-list">
            <span style={{ fontSize: "0.75rem", textTransform: "uppercase", color: "var(--text-muted)", fontWeight: "600", letterSpacing: "0.05em" }}>
              Quick Evaluation Logins
            </span>
            {DEMO_ACCOUNTS.map((acc) => (
              <button
                key={acc.role}
                type="button"
                className="demo-btn"
                disabled={authLoading}
                onClick={() => {
                  setAuthEmail(acc.email);
                  setAuthPassword(acc.password);
                  handleLogin(acc.email, acc.password);
                }}
              >
                <div>
                  <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                    <span className={`badge badge-role-${acc.role.toLowerCase()}`}>
                      {acc.role}
                    </span>
                    <span style={{ fontSize: "0.85rem", fontWeight: "600" }}>{acc.email}</span>
                  </div>
                  <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginTop: "0.2rem" }}>
                    {acc.description}
                  </div>
                </div>
                <Check size={16} style={{ color: "var(--text-muted)" }} />
              </button>
            ))}
          </div>
        </div>
      </div>
    );
  }

  // -------------------------------------------------------------
  // RENDER: AUTHENTICATED DASHBOARD
  // -------------------------------------------------------------
  const roleBadgeClass = `badge-role-${currentUser.role?.toLowerCase() || "viewer"}`;

  return (
    <div className="app-container">
      {/* Header */}
      <header className="header">
        <div className="brand-area">
          <div className="brand-icon">
            <ShieldAlert size={24} />
          </div>
          <div>
            <div className="brand-title">CloudLog Dashboard</div>
            <div className="brand-subtitle">Serverless Critical Log Analysis & Incident Detection</div>
          </div>
        </div>

        <div className="header-actions">
          {/* Auto Refresh Toggle */}
          <button
            className={`btn btn-secondary ${autoRefresh ? "active" : ""}`}
            style={{ fontSize: "0.75rem", padding: "0.35rem 0.65rem" }}
            onClick={() => setAutoRefresh(!autoRefresh)}
            title="Auto-refresh every 10 seconds"
          >
            <Radio size={14} color={autoRefresh ? "#10b981" : "#6b7280"} />
            {autoRefresh ? "Live (10s)" : "Paused"}
          </button>

          {/* Manual Refresh */}
          <button
            className="btn btn-secondary"
            onClick={() => loadDashboardData()}
            disabled={isRefreshing}
            title="Manual refresh"
          >
            <RefreshCw size={14} className={isRefreshing ? "spinning" : ""} />
            Refresh
          </button>

          {/* Trigger Incident / Simulate Button */}
          <button
            className="btn btn-primary"
            onClick={() => setShowSimModal(true)}
            disabled={currentUser?.role === "Viewer"}
            title={currentUser?.role === "Viewer" ? "Viewers cannot simulate logs" : "Simulate an incident live in AWS"}
            style={{
              background: "linear-gradient(135deg, #ef4444, #dc2626)",
              borderColor: "#ef4444",
              boxShadow: "0 0 12px rgba(239, 68, 68, 0.35)",
              fontWeight: "600",
              display: "inline-flex",
              alignItems: "center",
              gap: "0.4rem",
            }}
          >
            <Zap size={14} />
            <span>Trigger Incident</span>
          </button>

          {/* User Session Pill */}
          <div className="user-pill">
            <User size={14} />
            <span>{currentUser.email}</span>
            <span className={`badge ${roleBadgeClass}`}>{currentUser.role}</span>
          </div>

          {/* Sign Out */}
          <button
            className="btn btn-secondary"
            onClick={handleLogout}
            title="Sign out of CloudLog"
          >
            <LogOut size={14} />
          </button>
        </div>
      </header>

      {/* Action Notification Banners */}
      {actionError && (
        <div style={{ padding: "0.75rem 1rem", background: "rgba(239, 68, 68, 0.15)", border: "1px solid rgba(239, 68, 68, 0.3)", borderRadius: "8px", color: "#f87171", fontSize: "0.85rem", marginBottom: "1.25rem", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span>{actionError}</span>
          <button onClick={() => setActionError(null)} style={{ background: "none", border: "none", color: "#f87171", cursor: "pointer" }}>
            <X size={16} />
          </button>
        </div>
      )}
      {actionSuccess && (
        <div style={{ padding: "0.75rem 1rem", background: "rgba(16, 185, 129, 0.15)", border: "1px solid rgba(16, 185, 129, 0.3)", borderRadius: "8px", color: "#34d399", fontSize: "0.85rem", marginBottom: "1.25rem", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span>{actionSuccess}</span>
          <button onClick={() => setActionSuccess(null)} style={{ background: "none", border: "none", color: "#34d399", cursor: "pointer" }}>
            <X size={16} />
          </button>
        </div>
      )}

      {/* KPI Cards Row */}
      <div className="kpi-grid">
        <div className="kpi-card">
          <div className="kpi-icon-box" style={{ background: "rgba(59, 130, 246, 0.15)", color: "#3b82f6" }}>
            <Database size={24} />
          </div>
          <div>
            <div className="kpi-title">Total Logs Ingested</div>
            <div className="kpi-value">{stats?.total_events ?? "—"}</div>
          </div>
        </div>

        <div className="kpi-card" style={{ borderColor: stats?.critical_events > 0 ? "rgba(239, 68, 68, 0.3)" : undefined }}>
          <div className="kpi-icon-box" style={{ background: "rgba(239, 68, 68, 0.15)", color: "#ef4444" }}>
            <Flame size={24} />
          </div>
          <div>
            <div className="kpi-title">Critical Events</div>
            <div className="kpi-value" style={{ color: "#f87171" }}>
              {stats?.critical_events ?? "—"}
            </div>
          </div>
        </div>

        <div className="kpi-card">
          <div className="kpi-icon-box" style={{ background: "rgba(249, 115, 22, 0.15)", color: "#f97316" }}>
            <AlertTriangle size={24} />
          </div>
          <div>
            <div className="kpi-title">Error Logs</div>
            <div className="kpi-value" style={{ color: "#fb923c" }}>
              {stats?.error_events ?? "—"}
            </div>
          </div>
        </div>

        <div className="kpi-card" style={{ borderColor: stats?.open_incidents > 0 ? "rgba(245, 158, 11, 0.3)" : undefined }}>
          <div className="kpi-icon-box" style={{ background: "rgba(245, 158, 11, 0.15)", color: "#f59e0b" }}>
            <Activity size={24} />
          </div>
          <div>
            <div className="kpi-title">Open Incidents</div>
            <div className="kpi-value" style={{ color: "#fbbf24" }}>
              {stats?.open_incidents ?? "—"}
            </div>
          </div>
        </div>
      </div>

      {/* Main Content Grid */}
      <div className="dashboard-grid">
        {/* Left Column: Incidents Management & Telemetry */}
        <div style={{ display: "flex", flexDirection: "column", gap: "1.5rem" }}>
          {/* Incident Queue */}
          <div className="panel">
            <div className="section-header">
              <div className="section-title">
                <Flame size={18} color="#ef4444" />
                <span>Incident Response Queue</span>
                <span className="badge badge-critical" style={{ fontSize: "0.65rem", padding: "0.1rem 0.4rem" }}>
                  {incidents.length}
                </span>
              </div>

              {/* Tab Group */}
              <div className="tab-group">
                {["ALL", "OPEN", "RESOLVED"].map((tab) => (
                  <button
                    key={tab}
                    className={`tab-btn ${incidentTab === tab ? "active" : ""}`}
                    onClick={() => setIncidentTab(tab)}
                  >
                    {tab}
                  </button>
                ))}
              </div>
            </div>

            {incidents.length === 0 ? (
              <div style={{ padding: "2.5rem 1rem", textAlign: "center", color: "var(--text-muted)" }}>
                <CheckCircle2 size={32} color="#10b981" style={{ margin: "0 auto 0.5rem" }} />
                <p>No incidents found matching current filter.</p>
              </div>
            ) : (
              <div style={{ overflowX: "auto" }}>
                <table>
                  <thead>
                    <tr>
                      <th>Status</th>
                      <th>Severity</th>
                      <th>Service</th>
                      <th>Message</th>
                      <th>Created At</th>
                      <th style={{ textAlign: "right" }}>Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {incidents.map((inc) => {
                      const isOpen = inc.status === "OPEN";
                      const isCritical = inc.severity === "CRITICAL";
                      return (
                        <tr
                          key={inc.incident_id}
                          style={{ cursor: "pointer" }}
                          onClick={() => setSelectedIncident(inc)}
                        >
                          <td>
                            <span className={`badge ${isOpen ? "badge-open" : "badge-resolved"}`}>
                              {inc.status}
                            </span>
                          </td>
                          <td>
                            <span className={`badge ${isCritical ? "badge-critical" : "badge-error"}`}>
                              {inc.severity}
                            </span>
                          </td>
                          <td className="mono" style={{ fontWeight: "600", color: "#93c5fd" }}>
                            {inc.service}
                          </td>
                          <td style={{ maxWidth: "260px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={inc.message}>
                            {inc.message}
                          </td>
                          <td style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
                            {new Date(inc.created_at).toLocaleTimeString()}
                          </td>
                          <td style={{ textAlign: "right" }} onClick={(e) => e.stopPropagation()}>
                            {isOpen ? (
                              <button
                                className="btn btn-resolve"
                                disabled={currentUser.role === "Viewer" || resolvingId === inc.incident_id}
                                onClick={() => handleResolve(inc.incident_id)}
                                title={currentUser.role === "Viewer" ? "Viewers cannot resolve incidents" : "Mark as Resolved"}
                              >
                                {resolvingId === inc.incident_id ? (
                                  <RefreshCw size={12} className="spinning" />
                                ) : (
                                  <Check size={12} />
                                )}
                                Resolve
                              </button>
                            ) : (
                              <span style={{ fontSize: "0.75rem", color: "#10b981", display: "inline-flex", alignItems: "center", gap: "0.25rem" }}>
                                <CheckCircle2 size={12} /> Closed
                              </span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Telemetry Stream */}
          <div className="panel">
            <div className="section-header" style={{ flexWrap: "wrap", gap: "0.75rem" }}>
              <div className="section-title">
                <FileText size={18} color="#3b82f6" />
                <span>Live Telemetry Stream</span>
              </div>

              {/* Filters */}
              <div style={{ display: "flex", gap: "0.5rem" }}>
                {/* Service Filter */}
                <select
                  value={filterService}
                  onChange={(e) => setFilterService(e.target.value)}
                  style={{ fontSize: "0.75rem", padding: "0.3rem 0.6rem" }}
                >
                  <option value="">All Services</option>
                  {services.map((svc) => (
                    <option key={svc} value={svc}>
                      {svc}
                    </option>
                  ))}
                </select>

                {/* Level Filter */}
                <select
                  value={filterLevel}
                  onChange={(e) => setFilterLevel(e.target.value)}
                  style={{ fontSize: "0.75rem", padding: "0.3rem 0.6rem" }}
                >
                  <option value="">All Levels</option>
                  <option value="CRITICAL">CRITICAL</option>
                  <option value="ERROR">ERROR</option>
                  <option value="WARNING">WARNING</option>
                  <option value="INFO">INFO</option>
                </select>
              </div>
            </div>

            {events.length === 0 ? (
              <div style={{ padding: "2rem", textAlign: "center", color: "var(--text-muted)" }}>
                No telemetry logs matching selected filters.
              </div>
            ) : (
              <div style={{ overflowX: "auto" }}>
                <table>
                  <thead>
                    <tr>
                      <th>Time</th>
                      <th>Level</th>
                      <th>Service</th>
                      <th>Message</th>
                      <th>Event ID</th>
                    </tr>
                  </thead>
                  <tbody>
                    {events.map((evt) => {
                      const levelClass = `badge-${evt.level?.toLowerCase() || "info"}`;
                      return (
                        <tr key={evt.event_id}>
                          <td style={{ fontSize: "0.75rem", color: "var(--text-muted)", whiteSpace: "nowrap" }}>
                            {new Date(evt.timestamp).toLocaleTimeString()}
                          </td>
                          <td>
                            <span className={`badge ${levelClass}`}>{evt.level}</span>
                          </td>
                          <td className="mono" style={{ color: "#93c5fd", fontWeight: "500" }}>
                            {evt.service}
                          </td>
                          <td style={{ maxWidth: "340px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={evt.message}>
                            {evt.message}
                          </td>
                          <td className="mono" style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
                            {evt.event_id?.slice(0, 12)}...
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>

        {/* Right Column: System Breakdown & Pipeline Diagnostics */}
        <div style={{ display: "flex", flexDirection: "column", gap: "1.5rem" }}>
          {/* Telemetry Breakdown */}
          <div className="panel">
            <div className="section-header">
              <div className="section-title">
                <Activity size={18} color="#8b5cf6" />
                <span>Severity Distribution</span>
              </div>
            </div>

            {(() => {
              const total = stats?.total_events || 0;
              const criticalCount = stats?.critical_events || 0;
              const errorCount = stats?.error_events || 0;
              const otherCount = Math.max(0, total - criticalCount - errorCount);

              const critPct = total > 0 ? Math.round((criticalCount / total) * 100) : 0;
              const errPct = total > 0 ? Math.round((errorCount / total) * 100) : 0;
              const otherPct = total > 0 ? Math.round((otherCount / total) * 100) : 0;

              return (
                <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
                  <div className="breakdown-item">
                    <div className="breakdown-header">
                      <span style={{ color: "#f87171", fontWeight: "600" }}>CRITICAL</span>
                      <span>{criticalCount} ({critPct}%)</span>
                    </div>
                    <div className="breakdown-bar-bg">
                      <div className="breakdown-bar-fill" style={{ width: `${critPct}%`, background: "#ef4444" }} />
                    </div>
                  </div>

                  <div className="breakdown-item">
                    <div className="breakdown-header">
                      <span style={{ color: "#fb923c", fontWeight: "600" }}>ERROR</span>
                      <span>{errorCount} ({errPct}%)</span>
                    </div>
                    <div className="breakdown-bar-bg">
                      <div className="breakdown-bar-fill" style={{ width: `${errPct}%`, background: "#f97316" }} />
                    </div>
                  </div>

                  <div className="breakdown-item">
                    <div className="breakdown-header">
                      <span style={{ color: "#22d3ee", fontWeight: "600" }}>INFO / WARNING</span>
                      <span>{otherCount} ({otherPct}%)</span>
                    </div>
                    <div className="breakdown-bar-bg">
                      <div className="breakdown-bar-fill" style={{ width: `${otherPct}%`, background: "#06b6d4" }} />
                    </div>
                  </div>
                </div>
              );
            })()}
          </div>

          {/* Active Services List */}
          <div className="panel">
            <div className="section-header">
              <div className="section-title">
                <Server size={18} color="#10b981" />
                <span>Monitored Services</span>
              </div>
              <span className="badge badge-info">{services.length} Online</span>
            </div>

            {services.length === 0 ? (
              <p style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>
                No active services discovered yet. Upload a log batch to begin.
              </p>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
                {services.map((svc) => (
                  <div
                    key={svc}
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      padding: "0.6rem 0.85rem",
                      background: "rgba(255, 255, 255, 0.02)",
                      border: "1px solid var(--border-color)",
                      borderRadius: "8px",
                      cursor: "pointer",
                    }}
                    onClick={() => setFilterService(filterService === svc ? "" : svc)}
                  >
                    <span className="mono" style={{ fontSize: "0.85rem", fontWeight: "600", color: filterService === svc ? "#3b82f6" : "var(--text-primary)" }}>
                      {svc}
                    </span>
                    <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
                      {filterService === svc ? "Active Filter" : "Filter"}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Serverless Architecture Health Card */}
          <div className="panel">
            <div className="section-header">
              <div className="section-title">
                <CheckCircle2 size={18} color="#10b981" />
                <span>Architecture Health</span>
              </div>
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem", fontSize: "0.8rem" }}>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <span style={{ color: "var(--text-muted)" }}>Storage Ingestion (S3)</span>
                <span style={{ color: "#10b981", fontWeight: "600" }}>Active Trigger</span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <span style={{ color: "var(--text-muted)" }}>Log Processor (Lambda)</span>
                <span style={{ color: "#10b981", fontWeight: "600" }}>Deterministic Engine</span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <span style={{ color: "var(--text-muted)" }}>Storage Engine (DynamoDB)</span>
                <span style={{ color: "#10b981", fontWeight: "600" }}>Dual Table + GSI</span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <span style={{ color: "var(--text-muted)" }}>Alert Dispatcher (SNS)</span>
                <span style={{ color: "#10b981", fontWeight: "600" }}>Immediate Push</span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <span style={{ color: "var(--text-muted)" }}>RBAC Authorization</span>
                <span style={{ color: "#8b5cf6", fontWeight: "600" }}>Cognito JWT</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Incident Detail Modal */}
      {selectedIncident && (
        <div className="modal-backdrop" onClick={() => setSelectedIncident(null)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                <Flame size={20} color={selectedIncident.severity === "CRITICAL" ? "#ef4444" : "#f97316"} />
                <h3 style={{ fontSize: "1.1rem", fontWeight: "700" }}>Incident Details</h3>
              </div>
              <button
                onClick={() => setSelectedIncident(null)}
                style={{ background: "none", border: "none", color: "var(--text-muted)", cursor: "pointer" }}
              >
                <X size={20} />
              </button>
            </div>

            <div className="modal-body">
              <div className="modal-row">
                <span className="label">Incident ID</span>
                <span className="mono" style={{ fontSize: "0.8rem", color: "#93c5fd" }}>
                  {selectedIncident.incident_id}
                </span>
              </div>

              <div className="modal-row">
                <span className="label">Status</span>
                <div>
                  <span className={`badge ${selectedIncident.status === "OPEN" ? "badge-open" : "badge-resolved"}`}>
                    {selectedIncident.status}
                  </span>
                </div>
              </div>

              <div className="modal-row">
                <span className="label">Severity</span>
                <div>
                  <span className={`badge ${selectedIncident.severity === "CRITICAL" ? "badge-critical" : "badge-error"}`}>
                    {selectedIncident.severity}
                  </span>
                </div>
              </div>

              <div className="modal-row">
                <span className="label">Service</span>
                <span className="mono" style={{ fontWeight: "600" }}>
                  {selectedIncident.service}
                </span>
              </div>

              <div className="modal-row">
                <span className="label">Error Code</span>
                <span className="mono" style={{ color: selectedIncident.error_code ? "#f87171" : "var(--text-muted)" }}>
                  {selectedIncident.error_code || "None Specified"}
                </span>
              </div>

              <div className="modal-row">
                <span className="label">Message</span>
                <div style={{ background: "rgba(0,0,0,0.3)", padding: "0.6rem 0.75rem", borderRadius: "6px", border: "1px solid var(--border-color)", wordBreak: "break-word" }}>
                  {selectedIncident.message}
                </div>
              </div>

              <div className="modal-row">
                <span className="label">Trigger Event ID</span>
                <span className="mono" style={{ fontSize: "0.8rem", color: "var(--text-secondary)" }}>
                  {selectedIncident.source_event_id || "N/A"}
                </span>
              </div>

              <div className="modal-row">
                <span className="label">Source S3 URI</span>
                <span className="mono" style={{ fontSize: "0.75rem", color: "var(--text-secondary)", wordBreak: "break-all" }}>
                  {selectedIncident.source_s3_uri || "N/A"}
                </span>
              </div>

              <div className="modal-row">
                <span className="label">Detected At</span>
                <span>{new Date(selectedIncident.created_at).toLocaleString()}</span>
              </div>

              {selectedIncident.resolved_at && (
                <>
                  <div className="modal-row">
                    <span className="label">Resolved At</span>
                    <span>{new Date(selectedIncident.resolved_at).toLocaleString()}</span>
                  </div>
                  <div className="modal-row">
                    <span className="label">Resolved By</span>
                    <span style={{ color: "#34d399" }}>{selectedIncident.resolved_by}</span>
                  </div>
                </>
              )}
            </div>

            <div className="modal-footer">
              <button className="btn btn-secondary" onClick={() => setSelectedIncident(null)}>
                Close
              </button>
              {selectedIncident.status === "OPEN" && (
                <button
                  className="btn btn-primary"
                  disabled={currentUser.role === "Viewer" || resolvingId === selectedIncident.incident_id}
                  onClick={() => handleResolve(selectedIncident.incident_id)}
                >
                  {resolvingId === selectedIncident.incident_id ? (
                    <RefreshCw size={14} className="spinning" />
                  ) : (
                    <Check size={14} />
                  )}
                  {currentUser.role === "Viewer" ? "Read-Only (Viewer)" : "Resolve Incident"}
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Simulator Modal */}
      {showSimModal && (
        <div className="modal-backdrop" onClick={() => !simulating && setShowSimModal(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()} style={{ maxWidth: "600px" }}>
            <div className="modal-header">
              <div style={{ display: "flex", alignItems: "center", gap: "0.6rem" }}>
                <div style={{ background: "rgba(239, 68, 68, 0.15)", padding: "0.4rem", borderRadius: "8px", display: "flex", color: "#ef4444" }}>
                  <Zap size={20} />
                </div>
                <div>
                  <h3 style={{ fontSize: "1.15rem", fontWeight: "700" }}>Live Incident Simulator</h3>
                  <p style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginTop: "0.15rem" }}>
                    Injects a real .jsonl log to Amazon S3 → Triggers Lambda analysis & SNS alerts
                  </p>
                </div>
              </div>
              <button
                onClick={() => setShowSimModal(false)}
                disabled={simulating}
                style={{ background: "none", border: "none", color: "var(--text-muted)", cursor: "pointer" }}
              >
                <X size={20} />
              </button>
            </div>

            {/* Quick Presets */}
            <div style={{ marginBottom: "1.25rem" }}>
              <span style={{ fontSize: "0.75rem", textTransform: "uppercase", color: "var(--text-muted)", fontWeight: "600", letterSpacing: "0.05em", display: "block", marginBottom: "0.5rem" }}>
                Quick Scenario Presets (1-Click)
              </span>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.5rem" }}>
                <button
                  type="button"
                  className="demo-btn"
                  style={{ padding: "0.6rem 0.75rem" }}
                  onClick={() => {
                    setSimService("database-cluster");
                    setSimLevel("CRITICAL");
                    setSimErrorCode("CRIT_DB_DEADLOCK");
                    setSimMessage("Database deadlock detected on write replica during checkout commit");
                  }}
                >
                  <div>
                    <div style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
                      <span className="badge badge-critical" style={{ fontSize: "0.65rem", padding: "0.1rem 0.35rem" }}>CRITICAL</span>
                      <span style={{ fontSize: "0.8rem", fontWeight: "600" }}>DB Deadlock</span>
                    </div>
                    <div style={{ fontSize: "0.7rem", color: "var(--text-muted)", marginTop: "0.2rem" }}>
                      Triggers SNS alert + Open Incident
                    </div>
                  </div>
                </button>

                <button
                  type="button"
                  className="demo-btn"
                  style={{ padding: "0.6rem 0.75rem" }}
                  onClick={() => {
                    setSimService("payment-gateway");
                    setSimLevel("ERROR");
                    setSimErrorCode("ERR_PAYMENT_TIMEOUT");
                    setSimMessage("Payment provider HTTP 504 Gateway Timeout on credit card capture batch");
                  }}
                >
                  <div>
                    <div style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
                      <span className="badge badge-error" style={{ fontSize: "0.65rem", padding: "0.1rem 0.35rem" }}>ERROR</span>
                      <span style={{ fontSize: "0.8rem", fontWeight: "600" }}>Payment 504</span>
                    </div>
                    <div style={{ fontSize: "0.7rem", color: "var(--text-muted)", marginTop: "0.2rem" }}>
                      Triggers High Severity Incident
                    </div>
                  </div>
                </button>

                <button
                  type="button"
                  className="demo-btn"
                  style={{ padding: "0.6rem 0.75rem" }}
                  onClick={() => {
                    setSimService("auth-service");
                    setSimLevel("WARNING");
                    setSimErrorCode("WARN_AUTH_BURST");
                    setSimMessage("Burst authentication requests exceeding rate limit for IP range 198.51.100.0/24");
                  }}
                >
                  <div>
                    <div style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
                      <span className="badge badge-warning" style={{ fontSize: "0.65rem", padding: "0.1rem 0.35rem" }}>WARNING</span>
                      <span style={{ fontSize: "0.8rem", fontWeight: "600" }}>Auth Burst</span>
                    </div>
                    <div style={{ fontSize: "0.7rem", color: "var(--text-muted)", marginTop: "0.2rem" }}>
                      Appears in Live Telemetry
                    </div>
                  </div>
                </button>

                <button
                  type="button"
                  className="demo-btn"
                  style={{ padding: "0.6rem 0.75rem" }}
                  onClick={() => {
                    setSimService("order-service");
                    setSimLevel("INFO");
                    setSimErrorCode("");
                    setSimMessage("Order processing queue drained successfully in 12ms (0 backlog)");
                  }}
                >
                  <div>
                    <div style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
                      <span className="badge badge-info" style={{ fontSize: "0.65rem", padding: "0.1rem 0.35rem" }}>INFO</span>
                      <span style={{ fontSize: "0.8rem", fontWeight: "600" }}>Routine Heartbeat</span>
                    </div>
                    <div style={{ fontSize: "0.7rem", color: "var(--text-muted)", marginTop: "0.2rem" }}>
                      Normal telemetry ingest
                    </div>
                  </div>
                </button>
              </div>
            </div>

            {/* Simulation Form */}
            <form onSubmit={handleSimulateSubmit} style={{ display: "flex", flexDirection: "column", gap: "0.9rem" }}>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.75rem" }}>
                <div>
                  <label style={{ display: "block", fontSize: "0.75rem", fontWeight: "600", textTransform: "uppercase", color: "var(--text-secondary)", marginBottom: "0.3rem" }}>
                    Service Name
                  </label>
                  <input
                    type="text"
                    required
                    value={simService}
                    onChange={(e) => setSimService(e.target.value)}
                    placeholder="database-cluster"
                    style={{ width: "100%", fontSize: "0.85rem", padding: "0.55rem 0.75rem" }}
                  />
                </div>

                <div>
                  <label style={{ display: "block", fontSize: "0.75rem", fontWeight: "600", textTransform: "uppercase", color: "var(--text-secondary)", marginBottom: "0.3rem" }}>
                    Log Level
                  </label>
                  <select
                    value={simLevel}
                    onChange={(e) => setSimLevel(e.target.value)}
                    style={{ width: "100%", fontSize: "0.85rem", padding: "0.55rem 0.75rem" }}
                  >
                    <option value="CRITICAL">CRITICAL (Triggers Incident + SNS)</option>
                    <option value="ERROR">ERROR (Triggers Incident)</option>
                    <option value="WARNING">WARNING</option>
                    <option value="INFO">INFO</option>
                  </select>
                </div>
              </div>

              <div>
                <label style={{ display: "block", fontSize: "0.75rem", fontWeight: "600", textTransform: "uppercase", color: "var(--text-secondary)", marginBottom: "0.3rem" }}>
                  Error Code (Optional)
                </label>
                <input
                  type="text"
                  value={simErrorCode}
                  onChange={(e) => setSimErrorCode(e.target.value)}
                  placeholder="CRIT_DB_DEADLOCK"
                  style={{ width: "100%", fontSize: "0.85rem", padding: "0.55rem 0.75rem" }}
                />
              </div>

              <div>
                <label style={{ display: "block", fontSize: "0.75rem", fontWeight: "600", textTransform: "uppercase", color: "var(--text-secondary)", marginBottom: "0.3rem" }}>
                  Log Message
                </label>
                <textarea
                  required
                  rows={3}
                  value={simMessage}
                  onChange={(e) => setSimMessage(e.target.value)}
                  placeholder="Description of the log message..."
                  style={{
                    width: "100%",
                    fontSize: "0.85rem",
                    padding: "0.55rem 0.75rem",
                    background: "rgba(255, 255, 255, 0.05)",
                    border: "1px solid var(--border-color)",
                    borderRadius: "8px",
                    color: "var(--text-primary)",
                    fontFamily: "inherit",
                    resize: "vertical",
                  }}
                />
              </div>

              <div className="modal-footer" style={{ marginTop: "0.5rem" }}>
                <button
                  type="button"
                  className="btn btn-secondary"
                  disabled={simulating}
                  onClick={() => setShowSimModal(false)}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={simulating || currentUser?.role === "Viewer"}
                  style={{
                    background: "linear-gradient(135deg, #ef4444, #dc2626)",
                    borderColor: "#ef4444",
                  }}
                >
                  {simulating ? (
                    <>
                      <RefreshCw size={14} className="spinning" /> Ingesting to S3...
                    </>
                  ) : (
                    <>
                      <Send size={14} /> Trigger in AWS Live
                    </>
                  )}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
