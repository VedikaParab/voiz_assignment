"""
a1_state_machine/app.py
Optional Streamlit UI — chat on left, live state on right.
Run:  streamlit run a1_state_machine/app.py
"""

import json
import streamlit as st
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config import chat, get_logger
from a1_state_machine.state_machine import init_call_state, state_injector, Phase, TERMINAL_PHASES
from a1_state_machine.goal_hierarchy import evaluate_goal_hierarchy
from a1_state_machine.phase_transitions import phase_transition_engine
from a1_state_machine.diversion_recovery import get_diversion_utterance, reset_diversion_index
from a1_state_machine.conversation_loop import (
    AGENT_BASE_PROMPT, OBJECTION_KEYWORDS, DIVERSION_KEYWORDS,
    build_system_prompt,
)

get_logger("a1", "voiz_a1.jsonl")

st.set_page_config(page_title="VOIZ A1 — State Machine", layout="wide")
st.title("VOIZ Call State Machine")

# ── Session state init ─────────────────────────────────────────────────
if "call_state" not in st.session_state:
    st.session_state.call_state = init_call_state()
    reset_diversion_index()
if "history" not in st.session_state:
    st.session_state.history = []
if "messages" not in st.session_state:
    st.session_state.messages = []

col_chat, col_state = st.columns([3, 2])

with col_chat:
    st.subheader("Conversation")
    for msg in st.session_state.messages:
        role = "You (Caller)" if msg["role"] == "user" else "VOIZ Agent"
        with st.chat_message(msg["role"]):
            st.write(f"**{role}:** {msg['content']}")

    state = st.session_state.call_state
    is_terminal = state.call_phase in TERMINAL_PHASES

    if not is_terminal:
        user_input = st.chat_input("Type caller utterance...")
        if user_input:
            if any(kw in user_input.lower() for kw in OBJECTION_KEYWORDS):
                state.objection_count += 1

            is_div = any(kw in user_input.lower() for kw in DIVERSION_KEYWORDS)
            if is_div:
                state.diversion_count += 1
                state.patience_budget -= 1

            state.current_goal = evaluate_goal_hierarchy(state)
            system_prompt = build_system_prompt(state)

            if is_div:
                hint = get_diversion_utterance(state.diversion_count)
                system_prompt += f'\n\nDIVERSION RECOVERY: Start your response with: "{hint}"'

            st.session_state.history.append({"role": "user", "content": user_input})
            st.session_state.messages.append({"role": "user", "content": user_input})

            with st.spinner("Agent thinking..."):
                response = chat(
                    system=system_prompt,
                    messages=st.session_state.history,
                    max_tokens=200,
                )

            st.session_state.history.append({"role": "assistant", "content": response})
            st.session_state.messages.append({"role": "assistant", "content": response})

            old_phase = state.call_phase
            # phase_transition_engine also populates confirmed_data
            state.call_phase = phase_transition_engine(state.call_phase, response, state)
            if state.call_phase == Phase.ESCALATE:
                state.escalation_flag = True

            st.session_state.call_state = state
            st.rerun()
    else:
        st.info(f"Call ended — final phase: **{state.call_phase.value}**")
        if st.button("Start new call"):
            st.session_state.call_state = init_call_state()
            st.session_state.history = []
            st.session_state.messages = []
            reset_diversion_index()
            st.rerun()

with col_state:
    st.subheader("Live Call State")
    s = st.session_state.call_state
    phase_colors = {
        "INTRO": "blue", "VERIFICATION": "orange", "PITCH": "green",
        "NEGOTIATION": "violet", "CAPTURE": "green", "CLOSE": "green",
        "ESCALATE": "red",
    }
    color = phase_colors.get(s.call_phase.value, "gray")
    st.markdown(f"**Phase:** :{color}[{s.call_phase.value}]")
    st.markdown(f"**Goal:** `{s.current_goal}`")

    col1, col2, col3 = st.columns(3)
    col1.metric("Objections", s.objection_count)
    col2.metric("Diversions", s.diversion_count)
    col3.metric("Patience", s.patience_budget)

    if s.escalation_flag:
        st.error("ESCALATION FLAG — hand off to human agent")

    if s.confirmed_data:
        st.markdown("**Confirmed data:**")
        st.json(s.confirmed_data)

    st.markdown("---")
    st.markdown("**Full state JSON:**")
    st.json(s.to_dict())

    st.markdown("**State injected into prompt:**")
    st.code(state_injector(s), language="text")