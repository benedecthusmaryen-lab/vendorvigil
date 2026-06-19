import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  checkHealth,
  getActiveAssessment,
  getLatestAssessment,
  getDashboardSummary,
  streamAssessmentEvents,
} from '../api';
import '../Dashboard.css';

// Agent display config — PNG inset icons placeholder; replace with SVGs
const AGENT_CONFIG = [
  { key: 'coordinator', label: 'Coordinator', color: '#6366f1' },
  { key: 'security',    label: 'Security',    color: '#ef4444' },
  { key: 'privacy',     label: 'Privacy',     color: '#8b5cf6' },
  { key: 'financial',   label: 'Financial',   color: '#f59e0b' },
  { key: 'risk',        label: 'Risk Scorer', color: '#06b6d4' },
  { key: 'audit',       label: 'Audit',       color: '#64748b' },
  { key: 'report',      label: 'Report',      color: '#10b981' },
];

const STATUS_COLORS = {
  APPROVED:             { bg: '#dcfce7', text: '#166534', border: '#86efac' },
  NEEDS_REVISION:       { bg: '#fef9c3', text: '#854d0e', border: '#fde047' },
  ESCALATED:            { bg: '#fee2e2', text: '#991b1b', border: '#fca5a5' },
  TEMPORARILY_REJECTED: { bg: '#fef2f2', text: '#7f1d1d', border: '#fca5a5' },
};

function AgentIcon({ status, index }) {
  if (status === 'done') return <span className="agent-icon icon-done">&#10003;</span>;
  if (status === 'running') return <span className="agent-icon icon-running">&#8635;</span>;
  if (status === 'skipped') return <span className="agent-icon icon-skipped">&#8212;</span>;
  if (status === 'failed') return <span className="agent-icon icon-failed">&#10007;</span>;
  return <span className="agent-icon icon-waiting">{index + 1}</span>;
}

function AgentTimeline({ agents }) {
  return (
    <div className="agent-timeline">
      <h3 className="section-title">Agent Progress</h3>
      <div className="timeline-track">
        {AGENT_CONFIG.map((cfg, i) => {
          const agent = agents?.[cfg.key] || {};
          const status = agent.status || 'waiting';
          return (
            <div key={cfg.key} className={`timeline-node timeline-${status}`}>
              <div className="timeline-dot" style={{ borderColor: cfg.color }}>
                <AgentIcon status={status} index={i} />
              </div>
              <div className="timeline-content">
                <span className="timeline-label">{cfg.label}</span>
                <span className={`status-badge badge-${status}`}>{status}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ScoreRing({ score, size = 120, label, color }) {
  const r = (size - 12) / 2;
  const circ = 2 * Math.PI * r;
  const offset = circ - (score / 100) * circ;
  const ringColor = color || (score >= 70 ? '#10b981' : score >= 50 ? '#f59e0b' : '#ef4444');

  return (
    <div className="score-ring-wrap">
      <svg width={size} height={size} className="score-ring">
        <circle cx={size / 2} cy={size / 2} r={r} className="ring-bg" />
        <circle
          cx={size / 2} cy={size / 2} r={r}
          className="ring-fill" stroke={ringColor}
          strokeDasharray={circ} strokeDashoffset={offset}
        />
      </svg>
      <div className="score-ring-label">
        <span className="score-value" style={{ color: ringColor }}>{score}</span>
        {label && <span className="score-name">{label}</span>}
      </div>
    </div>
  );
}

function AssessmentView({ session }) {
  const agents = session?.agents || {};
  const chatMessages = session?.chat_messages || [];

  const getScore = (role) => {
    const result = agents[role]?.result;
    if (!result) return null;
    return result.score || result.total_score || null;
  };

  const securityScore = getScore('security');
  const privacyScore = getScore('privacy');
  const financialScore = getScore('financial');

  const riskResult = agents.risk?.result;
  const riskStatus = riskResult?.status || riskResult?.decision_status || '';
  const totalScore = riskResult?.total_score || riskResult?.score || 0;
  const statusStyle = STATUS_COLORS[riskStatus] || STATUS_COLORS.NEEDS_REVISION;

  const reportResult = agents.report?.result;
  const auditResult = agents.audit?.result;

  const statusLabel = session.status === 'completed' ? 'Completed'
    : session.status === 'failed' ? 'Failed'
    : session.status === 'running' ? 'In Progress'
    : 'Queued';

  return (
    <div className="assessment-view">
      {/* Executive Status */}
      <div className="executive-status">
        <div className="exec-left">
          <h2 className="exec-vendor">{session.vendor_name}</h2>
          <span className="exec-status-badge" style={{
            background: statusStyle.bg, color: statusStyle.text, borderColor: statusStyle.border,
          }}>{riskStatus || statusLabel}</span>
          {riskResult?.human_review_required && (
            <span className="human-review-badge">Human Review Required</span>
          )}
        </div>
        <div className="exec-right">
          <ScoreRing score={totalScore} size={140} />
        </div>
      </div>

      {/* Agent Timeline */}
      <AgentTimeline agents={agents} />

      {/* Score Cards */}
      {(securityScore !== null || privacyScore !== null || financialScore !== null) && (
        <div className="score-section">
          <h3 className="section-title">Domain Scores</h3>
          <div className="score-grid">
            {securityScore !== null && (
              <div className="score-card"><ScoreRing score={securityScore} size={90} color="#ef4444" /><span>Security</span></div>
            )}
            {privacyScore !== null && (
              <div className="score-card"><ScoreRing score={privacyScore} size={90} color="#8b5cf6" /><span>Privacy</span></div>
            )}
            {financialScore !== null && (
              <div className="score-card"><ScoreRing score={financialScore} size={90} color="#f59e0b" /><span>Financial</span></div>
            )}
            {totalScore > 0 && (
              <div className="score-card"><ScoreRing score={totalScore} size={90} color="#06b6d4" /><span>Overall</span></div>
            )}
          </div>
        </div>
      )}

      {/* Key Findings */}
      {(riskResult?.reasons?.length > 0 || riskResult?.required_actions?.length > 0) && (
        <div className="findings-section">
          <h3 className="section-title">Key Findings</h3>
          {riskResult.reasons?.length > 0 && (
            <ul className="findings-list">
              {riskResult.reasons.map((r, i) => <li key={i}>{r}</li>)}
            </ul>
          )}
          {riskResult.required_actions?.length > 0 && (
            <ol className="actions-list">
              {riskResult.required_actions.map((a, i) => <li key={i}>{a}</li>)}
            </ol>
          )}
        </div>
      )}

      {/* Report Summary */}
      {reportResult?.executive_summary && (
        <div className="report-section">
          <h3 className="section-title">Executive Summary</h3>
          <p className="report-summary">{reportResult.executive_summary}</p>
          {reportResult.recommendations?.length > 0 && (
            <ol className="recs-list">
              {reportResult.recommendations.map((r, i) => <li key={i}>{r}</li>)}
            </ol>
          )}
        </div>
      )}

      {/* Audit Record */}
      {auditResult && (
        <div className="audit-section">
          <h3 className="section-title">Audit Record</h3>
          <div className="audit-meta">
            <span className="audit-id-label">ID: {auditResult.audit_id}</span>
            <span>Status: {auditResult.decision_status}</span>
            <span>Score: {auditResult.total_score}/100</span>
          </div>
          {auditResult.disclaimer && (
            <p className="disclaimer">{auditResult.disclaimer}</p>
          )}
        </div>
      )}

      {/* Chat Transcript */}
      {chatMessages.length > 0 && (
        <div className="chat-section">
          <h3 className="section-title">Agent Conversation</h3>
          <div className="chat-messages">
            {chatMessages.map((msg, i) => (
              <div key={i} className="chat-msg">
                <span className="chat-sender">{msg.sender}</span>
                <div className="chat-body">{msg.content}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// =====================================================================
// Main Dashboard — Read-Only
// =====================================================================
export default function Dashboard() {
  const [assessment, setAssessment] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [apiStatus, setApiStatus] = useState('connecting');
  const cleanupRef = useRef(null);

  // Auto-discover assessment on mount
  useEffect(() => {
    let cancelled = false;

    async function discover() {
      try {
        await checkHealth();
        if (cancelled) return;
        setApiStatus('ok');

        // Try active first, then latest
        let activeResult = await getActiveAssessment();
        if (!cancelled && activeResult?.assessment) {
          setAssessment(activeResult.assessment);
          subscribeSSE(activeResult.assessment.assessment_id);
          setLoading(false);
          return;
        }

        let latestResult = await getLatestAssessment();
        if (!cancelled && latestResult?.assessment) {
          setAssessment(latestResult.assessment);
          setLoading(false);
          return;
        }

        setLoading(false);
      } catch (e) {
        if (!cancelled) {
          setApiStatus('error');
          setError(e.message);
          setLoading(false);
        }
      }
    }

    function subscribeSSE(assessmentId) {
      if (cleanupRef.current) cleanupRef.current();
      cleanupRef.current = streamAssessmentEvents(assessmentId, {
        onProgress: (data) => { if (!cancelled) setAssessment(data); },
        onCompleted: (data) => { if (!cancelled) setAssessment(data); },
        onFailed: (data) => { if (!cancelled) setAssessment(data); },
        onError: () => { /* EventSource auto-reconnects */ },
      });
    }

    discover();

    // Poll for new active assessment every 30s when idle
    const pollInterval = setInterval(async () => {
      if (!assessment || (assessment.status !== 'running' && assessment.status !== 'queued')) {
        try {
          const active = await getActiveAssessment();
          if (!cancelled && active?.assessment && (!assessment || active.assessment.assessment_id !== assessment.assessment_id)) {
            setAssessment(active.assessment);
            subscribeSSE(active.assessment.assessment_id);
          }
        } catch (e) { /* ignore polling errors */ }
      }
    }, 30000);

    return () => {
      cancelled = true;
      if (cleanupRef.current) cleanupRef.current();
      clearInterval(pollInterval);
    };
  }, []);

  return (
    <div className="dashboard">
      {/* Header */}
      <header className="dash-header">
        <div className="header-left">
          <svg className="header-logo" width="32" height="32" viewBox="0 0 32 32" fill="none">
            <rect width="32" height="32" rx="6" fill="#6366f1"/>
            <path d="M8 16h16M16 8v16" stroke="#fff" strokeWidth="2.5" strokeLinecap="round"/>
            <circle cx="16" cy="16" r="6" stroke="#fff" strokeWidth="2" fill="none"/>
          </svg>
          <h1>VendorVigil</h1>
          <span className="header-sub">Third-Party Risk Triage</span>
        </div>
        <div className="header-right">
          <span className={`status-dot status-${apiStatus}`} />
          <span className="status-label">
            {apiStatus === 'ok' ? 'Connected' : apiStatus === 'error' ? 'Disconnected' : 'Connecting...'}
          </span>
        </div>
      </header>

      <div className="dash-body">
        <main className="main-content">
          {/* Loading State */}
          {loading && (
            <div className="state-container">
              <div className="spinner" />
              <p className="state-message">Loading assessment data...</p>
            </div>
          )}

          {/* Error State */}
          {!loading && error && (
            <div className="state-container">
              <div className="state-icon error-icon">
                <svg width="48" height="48" viewBox="0 0 48 48" fill="none">
                  <circle cx="24" cy="24" r="22" stroke="#ef4444" strokeWidth="2"/>
                  <path d="M16 16l16 16M32 16L16 32" stroke="#ef4444" strokeWidth="2.5" strokeLinecap="round"/>
                </svg>
              </div>
              <h2>Connection Error</h2>
              <p className="state-message">Could not connect to the VendorVigil API. Make sure the backend server is running.</p>
              <button className="retry-btn" onClick={() => window.location.reload()}>Retry</button>
            </div>
          )}

          {/* Empty State — No Assessment Yet */}
          {!loading && !assessment && !error && (
            <div className="state-container">
              <div className="state-icon">
                <svg width="48" height="48" viewBox="0 0 48 48" fill="none">
                  <rect x="6" y="8" width="36" height="32" rx="4" stroke="#94a3b8" strokeWidth="2" fill="none"/>
                  <path d="M16 20h16M16 28h10" stroke="#94a3b8" strokeWidth="2" strokeLinecap="round"/>
                </svg>
              </div>
              <h2>No Assessments Yet</h2>
              <p className="state-message">
                Start a vendor assessment in the Band Chat Room. Live results will appear here automatically.
              </p>
            </div>
          )}

          {/* Active/Latest Assessment */}
          {assessment && <AssessmentView session={assessment} />}
        </main>
      </div>
    </div>
  );
}
