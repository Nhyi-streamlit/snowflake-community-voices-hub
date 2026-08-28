import streamlit as st

pg = st.navigation([
    st.Page("pages/0_Homepage.py",       title="Homepage",            icon="🏠"),
    st.Page("pages/1_Speaker_Portal.py", title="Speaker Portal",      icon="🎤"),
    st.Page("pages/2_Vendor_Portal.py",  title="Vendor Portal",       icon="🏟️"),
    st.Page("pages/3_Admin.py",          title="Admin Portal",        icon="🔐"),
    st.Page("pages/4_Navan_Portal.py",   title="Navan Travel Portal", icon="✈️"),
])
pg.run()
