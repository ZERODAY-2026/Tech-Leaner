import streamlit as st
import snowflake.connector

try:
    conn = snowflake.connector.connect(
        account=st.secrets["snowflake"]["account"],
        user=st.secrets["snowflake"]["user"],
        password=st.secrets["snowflake"]["password"],
        warehouse=st.secrets["snowflake"]["warehouse"],
        database=st.secrets["snowflake"]["database"],
        schema=st.secrets["snowflake"]["schema"],
        role=st.secrets["snowflake"]["role"]
    )

    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM STUDENT_MARKS"
    )

    print("Snowflake connected successfully!")
    for row in cursor.fetchall():
        print(row)

    cursor.close()
    conn.close()

except Exception as e:
    print("Connection failed:", e)