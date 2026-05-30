"""
app.py — VOIZ A4 Campaign Engine
Streamlit dashboard:
  - Tab 1: Campaign config (upload contacts, set windows, channel seq)
  - Tab 2: Live queue (top 10 by priority score)
  - Tab 3: Contact log (every attempt + outcome)
  - Tab 4: Analytics (4 metrics + charts)

Run: streamlit run app.py
"""

import json
import random
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))

from scorer import score_all
from priority_queue import CampaignPriorityQueue
from dnc_manager import DNCManager
from channel_sequencer import ChannelSequencer
from window_enforcer import WindowEnforcer, IST
from campaign_runner import CampaignRunner

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="VOIZ Campaign Engine",
    page_icon="📞",
    layout="wide",
    initial_sidebar_state="expanded",
)

DATA_DIR   = Path(__file__).parent / "data"
CONFIG_PATH = DATA_DIR / "channel_config.json"

# ── Session state ──────────────────────────────────────────────────────────────
if "runner" not in st.session_state:
    st.session_state.runner = None
if "loaded" not in st.session_state:
    st.session_state.loaded = False
if "running" not in st.session_state:
    st.session_state.running = False
if "contacts_raw" not in st.session_state:
    st.session_state.contacts_raw = None

# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.image("https://img.shields.io/badge/VOIZ-Campaign%20Engine-6C3CE4?style=for-the-badge", use_container_width=True)
    st.markdown("## 📋 Campaign Control")

    # Load contacts
    uploaded = st.file_uploader("Upload contacts.json", type=["json"])
    if uploaded:
        st.session_state.contacts_raw = json.loads(uploaded.read())
        st.success(f"✅ {len(st.session_state.contacts_raw)} contacts loaded")
    elif (DATA_DIR / "contacts.json").exists():
        if st.button("Load default contacts.json"):
            st.session_state.contacts_raw = json.loads((DATA_DIR / "contacts.json").read_text())
            st.success(f"✅ {len(st.session_state.contacts_raw)} contacts loaded")

    bypass_window = st.checkbox("Bypass time window (demo mode)", value=True)

    st.markdown("---")

    if st.session_state.contacts_raw and not st.session_state.loaded:
        if st.button("🚀 Start Campaign", type="primary"):
            runner = CampaignRunner(bypass_window=bypass_window)
            runner.load_contacts(st.session_state.contacts_raw)
            runner.start()
            st.session_state.runner = runner
            st.session_state.loaded = True
            st.rerun()

    if st.session_state.loaded:
        runner: CampaignRunner = st.session_state.runner
        st.metric("Queue depth", len(runner.pq))
        st.metric("Attempts", runner.attempt_count)

        n_dispatch = st.slider("Attempts to run", 1, 20, 5)
        if st.button("▶ Run Attempts"):
            for _ in range(n_dispatch):
                if len(runner.pq) == 0:
                    break
                runner.dispatch_next(force_window=True)
            st.rerun()

        st.markdown("---")
        st.markdown("### ⛔ Manual DNC")
        dnc_phone = st.text_input("Phone number to DNC")
        dnc_reason = st.text_input("Reason", value="manual_request")
        if st.button("Add to DNC"):
            if dnc_phone:
                runner.dnc.add(dnc_phone, reason=dnc_reason, source="dashboard")
                st.success(f"Added {dnc_phone} to DNC")

        st.markdown("---")
        if st.button("💾 Save Log"):
            path = runner.save_log()
            st.success(f"Saved: {path.name}")

        if st.button("🔄 Reset Campaign"):
            st.session_state.runner = None
            st.session_state.loaded = False
            st.session_state.contacts_raw = None
            st.rerun()

# ── Main content ───────────────────────────────────────────────────────────────
st.title("📞 VOIZ Campaign Engine — Dashboard")

if not st.session_state.loaded:
    st.info("👈 Upload contacts and start the campaign from the sidebar to begin.")

    # Show sample config
    st.markdown("### Channel Config Preview")
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            st.json(json.load(f))
    st.stop()

runner: CampaignRunner = st.session_state.runner

tab1, tab2, tab3, tab4 = st.tabs([
    "⚙️ Config", "📊 Live Queue", "📋 Contact Log", "📈 Analytics"
])

# ── Tab 1: Config ──────────────────────────────────────────────────────────────
with tab1:
    st.subheader("Campaign Configuration")
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**Campaign Details**")
        cfg = runner.config
        st.metric("Campaign", cfg.get("campaign_name", "—"))
        st.metric("Type", cfg.get("campaign_type", "—"))
        st.metric("Max attempts / contact", cfg.get("max_attempts_per_contact", "—"))
        st.metric("Callback hold (min)", cfg.get("callback_hold_minutes", "—"))

        pw = cfg.get("permitted_windows", {})
        st.markdown("**Permitted Windows**")
        st.write(f"Days: {', '.join(pw.get('days', []))}")
        st.write(f"Hours: {pw.get('start_hour_ist',9)}:00 – {pw.get('end_hour_ist',20)}:00 IST")

    with col2:
        st.markdown("**Channel Sequences**")
        seqs = cfg.get("channel_sequences", {})
        for outcome, steps in seqs.items():
            if steps:
                seq_str = " → ".join(f"{s['channel']}(+{s['delay_minutes']}min)" for s in steps)
                st.write(f"**{outcome}**: {seq_str}")
            else:
                st.write(f"**{outcome}**: No further action")

    st.markdown("---")
    st.markdown("**Edit Channel Config (JSON)**")
    config_text = st.text_area(
        "channel_config.json",
        value=json.dumps(runner.config, indent=2),
        height=300,
    )
    if st.button("Apply Config Changes"):
        try:
            new_cfg = json.loads(config_text)
            CONFIG_PATH.write_text(json.dumps(new_cfg, indent=2))
            runner.sequencer.reload_config()
            runner.config = new_cfg
            st.success("✅ Config reloaded (no restart needed)")
        except json.JSONDecodeError as e:
            st.error(f"Invalid JSON: {e}")

# ── Tab 2: Live Queue ──────────────────────────────────────────────────────────
with tab2:
    st.subheader("Live Priority Queue — Top 10")

    col_r, col_nba = st.columns([3, 1])
    with col_r:
        if st.button("🔄 Refresh Queue"):
            st.rerun()
    with col_nba:
        run_nba = st.button("🧠 Run NBA Engine", type="primary")

    top10 = runner.pq.peek_top_n(10)
    if top10:
        df = pd.DataFrame([{
            "Rank": i + 1,
            "ID": c["contact_id"],
            "Name": c["name"],
            "Score": round(c.get("priority_score", 0), 4),
            "DPD": c.get("dpd_bucket", 0),
            "Risk": c.get("risk_score", 0),
            "Propensity": c.get("propensity_score", 0),
            "Last Outcome": c.get("last_contact_outcome", "—"),
            "Channel": c.get("preferred_channel", "—"),
            "Language": c.get("language", "—"),
        } for i, c in enumerate(top10)])

        # Colour-code DPD
        def dpd_color(val):
            colors = {0: "", 30: "background-color: #fff3cd",
                      60: "background-color: #ffe0b2", 90: "background-color: #ffcdd2",
                      120: "background-color: #ef9a9a"}
            return colors.get(val, "")

        st.dataframe(
            df.style.map(dpd_color, subset=["DPD"]),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.warning("Queue is empty.")

    # NBA results
    if run_nba:
        with st.spinner("Calling Claude NBA engine..."):
            nba_result = runner.get_nba()

        if nba_result.get("error"):
            st.error(f"NBA engine error: {nba_result['error']}")
            st.info("Tip: Set GROQ_API_KEY in your .env file for NBA engine.")
        else:
            st.success(f"✅ NBA engine responded in {nba_result['latency_ms']}ms")
            st.markdown("### 🎯 Top 3 Recommended for Immediate Outreach")
            for item in nba_result.get("ranked", []):
                urgency_colors = {"critical": "🔴", "high": "🟠", "medium": "🟡"}
                icon = urgency_colors.get(item.get("urgency", "medium"), "⚪")
                with st.expander(f"{icon} Rank {item['rank']}: {item['contact_id']} — {item['name']}"):
                    st.write(f"**Channel**: {item.get('recommended_channel','?')} | **Urgency**: {item.get('urgency','?')}")
                    st.write(f"**Reasoning**: {item.get('reasoning','')}")

# ── Tab 3: Contact Log ─────────────────────────────────────────────────────────
with tab3:
    st.subheader("Contact Attempt Log")

    log = runner.attempt_log
    if not log:
        st.info("No attempts yet. Run some dispatches from the sidebar.")
    else:
        df_log = pd.DataFrame([{
            "Attempt": e["attempt_id"],
            "Time": e["timestamp"][11:19],
            "Contact": e["contact_id"],
            "Name": e["name"],
            "Channel": e["channel"],
            "Outcome": e["outcome"],
            "RPC": "✅" if e["is_rpc"] else "",
            "DPD": e["dpd_bucket"],
            "Score": round(e["priority_score"], 4),
            "Attempt #": e["attempt_num"],
            "Queue Depth": e["queue_depth"],
        } for e in reversed(log)])

        def outcome_color(val):
            return {
                "ANSWERED": "background-color: #c8e6c9",
                "NO_ANSWER": "background-color: #fff9c4",
                "CALLBACK_REQUESTED": "background-color: #b3e5fc",
                "DNC": "background-color: #ffcdd2",
            }.get(val, "")

        st.dataframe(
            df_log.style.map(outcome_color, subset=["Outcome"]),
            use_container_width=True,
            hide_index=True,
        )

        # Download log
        csv = df_log.to_csv(index=False)
        st.download_button("⬇ Download Log CSV", csv, "campaign_log.csv", "text/csv")

# ── Tab 4: Analytics ───────────────────────────────────────────────────────────
with tab4:
    st.subheader("Campaign Analytics")

    stats = runner.analytics()
    if not stats:
        st.info("No data yet. Run some dispatches first.")
    else:
        # 4 key metrics
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Contact Rate",    f"{stats['contact_rate']*100:.1f}%",
                  help="% of attempts that resulted in ANSWERED")
        c2.metric("RPC Rate",        f"{stats['rpc_rate']*100:.1f}%",
                  help="Right-Party Contact rate (payment commitment)")
        c3.metric("Total Attempts",  stats["total_attempts"])
        c4.metric("Queue Remaining", len(runner.pq))

        st.markdown("---")
        col_a, col_b = st.columns(2)

        # Channel effectiveness chart
        with col_a:
            st.markdown("**Channel Effectiveness**")
            ch_data = stats.get("channel_effectiveness", {})
            if ch_data:
                ch_df = pd.DataFrame([
                    {"Channel": ch, "Attempts": v["attempts"], "Answer Rate %": round(v["answer_rate"] * 100, 1)}
                    for ch, v in ch_data.items()
                ])
                st.bar_chart(ch_df.set_index("Channel")["Answer Rate %"])
                st.dataframe(ch_df, use_container_width=True, hide_index=True)

        # Queue depth over time
        with col_b:
            st.markdown("**Queue Depth Over Time**")
            snapshots = stats.get("queue_depth_over_time", [])
            if snapshots:
                depth_df = pd.DataFrame(snapshots).set_index("attempt")["depth"]
                st.line_chart(depth_df)

        st.markdown("---")
        # Outcome breakdown
        st.markdown("**Outcome Breakdown**")
        log = runner.attempt_log
        outcome_counts = {}
        for e in log:
            outcome_counts[e["outcome"]] = outcome_counts.get(e["outcome"], 0) + 1

        if outcome_counts:
            oc_df = pd.DataFrame([
                {"Outcome": k, "Count": v, "% of Total": round(v / len(log) * 100, 1)}
                for k, v in sorted(outcome_counts.items(), key=lambda x: -x[1])
            ])
            st.dataframe(oc_df, use_container_width=True, hide_index=True)

        # DNC stats
        dnc_stats = runner.dnc.stats()
        st.markdown("**DNC Status**")
        d1, d2 = st.columns(2)
        d1.metric("Total DNC Numbers", dnc_stats["total_dnc_numbers"])
        d2.metric("Pop-Time DNC Catches", dnc_stats["pop_time_catches"])