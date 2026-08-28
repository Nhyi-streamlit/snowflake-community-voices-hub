# Shared CSS injected on every page.
GLOBAL_CSS = """
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

  /* Apply Inter to explicit elements — deliberately excludes [class*="st-"]
     so Streamlit's own CSS (Material Symbols for icons) is never overridden */
  html, body,
  .stTextInput input, .stSelectbox select, .stMultiSelect,
  .stTextArea textarea, .stNumberInput input, .stRadio label, .stSlider,
  button, label, p, h1, h2, h3, h4, h5, h6,
  .stMarkdown, .stAlert, .stCaption,
  [data-testid="stMarkdownContainer"],
  [data-testid="stText"] {
    font-family: 'Inter', sans-serif !important;
  }

  /* Restore Material Symbols / Icons font for Streamlit icon spans.
     High specificity (0,1,3) beats the [class*="st-"] rule (0,1,0)
     when both have !important. */
  details > summary > span[class*="st-"],
  details > summary span[class*="st-emotion"] {
    font-family: "Material Symbols Rounded", "Material Icons" !important;
    font-style: normal;
    font-weight: normal;
    font-size: 24px;
    line-height: 1;
    letter-spacing: normal;
    text-transform: none;
    white-space: nowrap;
    direction: ltr;
    -webkit-font-feature-settings: 'liga';
    -webkit-font-smoothing: antialiased;
  }

  [data-testid="collapsedControl"] { display: none; }

  .page-hero {
    background: linear-gradient(135deg, #0E2346 0%, #1B3A6B 100%);
    padding: 48px 56px;
    border-radius: 16px;
    margin-bottom: 40px;
  }
  .page-hero .eyebrow {
    display: inline-block;
    background: rgba(41,181,232,0.2);
    color: #7ED8F6;
    border: 1px solid rgba(41,181,232,0.35);
    border-radius: 20px;
    padding: 3px 14px;
    font-size: 0.70rem;
    font-weight: 700;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    margin-bottom: 14px;
  }
  .page-hero h1 {
    color: #FFFFFF;
    font-size: 2.1rem;
    font-weight: 800;
    line-height: 1.2;
    margin-bottom: 10px;
  }
  .page-hero p {
    color: #A8D8F0;
    font-size: 1rem;
    max-width: 640px;
    margin: 0;
  }

  .step-label {
    display: inline-block;
    background: #EBF8FF;
    color: #29B5E8;
    border: 1px solid #BEE3F8;
    border-radius: 6px;
    padding: 2px 10px;
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.07em;
    text-transform: uppercase;
    margin-bottom: 8px;
  }
  .section-title {
    font-size: 1.15rem;
    font-weight: 700;
    color: #0E2346;
    margin: 4px 0;
  }
  .section-hint {
    font-size: 0.87rem;
    color: #718096;
    margin-bottom: 20px;
  }

  .success-box {
    background: linear-gradient(135deg, #0E2346, #1B3A6B);
    border-radius: 16px;
    padding: 72px 48px;
    text-align: center;
  }
  .success-box h2 { color: #FFFFFF; font-size: 2rem; font-weight: 800; margin-bottom: 10px; }
  .success-box p  { color: #A8D8F0; font-size: 1rem; margin-bottom: 0; }

  .id-box {
    background: #F0FFF4;
    border: 2px solid #68D391;
    border-radius: 10px;
    padding: 20px 28px;
    text-align: center;
    margin: 20px 0;
  }
  .id-box .label { font-size: 0.75rem; font-weight: 700; color: #276749; letter-spacing: 0.08em; text-transform: uppercase; }
  .id-box .id    { font-size: 1.8rem; font-weight: 800; color: #22543D; font-family: monospace !important; letter-spacing: 0.06em; }

  .status-badge {
    display: inline-block;
    padding: 4px 14px;
    border-radius: 20px;
    font-size: 0.78rem;
    font-weight: 700;
    letter-spacing: 0.05em;
    text-transform: uppercase;
  }
  .status-pending    { background: #FFFBEB; color: #B7791F; border: 1px solid #F6E05E; }
  .status-approved   { background: #F0FFF4; color: #276749; border: 1px solid #68D391; }
  .status-waitlisted { background: #EBF8FF; color: #2B6CB0; border: 1px solid #90CDF4; }
  .status-not-a-fit  { background: #FFF5F5; color: #9B2335; border: 1px solid #FEB2B2; }

  .info-card {
    background: #F7FAFC;
    border: 1px solid #E2E8F0;
    border-radius: 12px;
    padding: 24px 28px;
    margin-bottom: 16px;
  }
  .info-card h4 { font-size: 0.95rem; font-weight: 700; color: #0E2346; margin: 0 0 8px 0; }
  .info-card p  { font-size: 0.88rem; color: #4A5568; margin: 0; line-height: 1.6; }

  .stat-card {
    background: #0E2346;
    border-radius: 12px;
    padding: 24px 20px;
    text-align: center;
  }
  .stat-card .num   { font-size: 2.2rem; font-weight: 800; color: #29B5E8; }
  .stat-card .label { font-size: 0.8rem; font-weight: 600; color: #A8D8F0; text-transform: uppercase; letter-spacing: 0.07em; margin-top: 4px; }

  .divider { border: none; border-top: 1px solid #E2E8F0; margin: 32px 0; }
</style>
"""


def inject_css():
    import streamlit as st
    st.markdown(GLOBAL_CSS, unsafe_allow_html=True)
