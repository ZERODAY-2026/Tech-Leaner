import json
import re
from typing import Any

import streamlit as st
import snowflake.connector
from google import genai

# ============================================================
# DataMind — Talk to Your Data
# Streamlit + Google Gemma + Snowflake
# Two selectable data sources:
# 1) Student Marks (user-created table)
# 2) Snowflake Sample Data (TPC-H SF1)
# ============================================================

st.set_page_config(page_title="DataMind | Talk to Your Data", page_icon="📊", layout="wide")
st.title("📊 DataMind")
st.subheader("Talk to Your Data")
st.write(
    "Ask questions in everyday language. Google Gemma interprets the question, "
    "Snowflake computes the answer, and DataMind shows the SQL and returned rows."
)

# ---------------- Configuration and connections ----------------

def get_gemma_client():
    return genai.Client(api_key=st.secrets["gemma"]["api_key"])


def get_snowflake_connection():
    cfg = st.secrets["snowflake"]
    return snowflake.connector.connect(
        account=cfg["account"],
        user=cfg["user"],
        password=cfg["password"],
        warehouse=cfg["warehouse"],
        database=cfg["database"],
        schema=cfg["schema"],
        role=cfg["role"],
    )


def clean_json_response(text: str) -> dict[str, Any]:
    if not text:
        raise ValueError("The AI returned an empty response.")
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("The AI response was not valid JSON.")
    parsed = json.loads(cleaned[start:end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("The AI response must be a JSON object.")
    return parsed


def ask_gemma_for_intent(question: str, prompt: str, allowed_actions: set[str]) -> dict[str, Any]:
    client = get_gemma_client()
    model_name = st.secrets["gemma"]["model"]
    response = client.models.generate_content(
        model=model_name,
        contents=prompt + "\nUser question: " + question,
    )
    intent = clean_json_response(response.text or "")
    if intent.get("action") not in allowed_actions:
        raise ValueError("The AI selected an unsupported action.")
    return intent


# ---------------- Student Marks data source ----------------

STUDENT_ACTIONS = {
    "average_by_subject", "top_student", "lowest_student", "compare_subjects",
    "compare_students", "student_count", "subject_summary", "pass_count",
    "marks_for_student", "all_marks", "unsupported",
}

STUDENT_PROMPT = """ Classify a question for a student-marks database. Do not answer it and do not generate SQL. Return ONLY JSON with keys action, subject, student, student2, threshold. Columns: STUDENT_ID, STUDENT_NAME, SUBJECT, MARKS. Allowed actions: average_by_subject, top_student, lowest_student, compare_subjects, compare_students, student_count, subject_summary, pass_count, marks_for_student, all_marks, unsupported. Rules: - average_by_subject: average/mean marks in one subject. - top_student / lowest_student: highest/lowest mark in a subject. - compare_subjects: compare average marks for Python and SQL. - compare_students: compare two named students. - student_count: distinct student count. - subject_summary: count, average, min and max for a subject. - pass_count: count distinct students with marks >= threshold in a subject. - marks_for_student: records for one named student; all_marks: every mark record. - unsupported: unrelated or unclear requests. - Subject must be Python, SQL, another explicitly named subject, or null if omitted. - For pass_count use the threshold the user stated; if none, use 35. - Use null for fields not needed. For compare_students student is first name, student2 is second. Examples: Question: What is the average mark for Python? {"action":"average_by_subject","subject":"Python","student":null,"student2":null,"threshold":null} Question: Which subject has the higher average? {"action":"compare_subjects","subject":null,"student":null,"student2":null,"threshold":null} Question: Compare Ravi and Meena {"action":"compare_students","subject":null,"student":"Ravi","student2":"Meena","threshold":null} Question: Tell me a joke {"action":"unsupported","subject":null,"student":null,"student2":null,"threshold":null} """

STUDENT_SQL = {
    "average_by_subject": "SELECT SUBJECT, ROUND(AVG(MARKS), 2) AS AVERAGE_MARKS FROM STUDENT_MARKS WHERE UPPER(SUBJECT)=UPPER(%s) GROUP BY SUBJECT",
    "top_student": "SELECT STUDENT_NAME, SUBJECT, MARKS FROM STUDENT_MARKS WHERE UPPER(SUBJECT)=UPPER(%s) ORDER BY MARKS DESC, STUDENT_NAME LIMIT 1",
    "lowest_student": "SELECT STUDENT_NAME, SUBJECT, MARKS FROM STUDENT_MARKS WHERE UPPER(SUBJECT)=UPPER(%s) ORDER BY MARKS ASC, STUDENT_NAME LIMIT 1",
    "compare_subjects": "SELECT SUBJECT, ROUND(AVG(MARKS), 2) AS AVERAGE_MARKS FROM STUDENT_MARKS WHERE UPPER(SUBJECT) IN ('PYTHON','SQL') GROUP BY SUBJECT ORDER BY SUBJECT",
    "compare_students": "SELECT STUDENT_NAME, SUBJECT, MARKS FROM STUDENT_MARKS WHERE UPPER(STUDENT_NAME) IN (UPPER(%s),UPPER(%s)) ORDER BY SUBJECT, STUDENT_NAME",
    "student_count": "SELECT COUNT(DISTINCT STUDENT_ID) AS STUDENT_COUNT FROM STUDENT_MARKS",
    "subject_summary": "SELECT SUBJECT, COUNT(*) AS RECORD_COUNT, ROUND(AVG(MARKS),2) AS AVERAGE_MARKS, MIN(MARKS) AS LOWEST_MARKS, MAX(MARKS) AS HIGHEST_MARKS FROM STUDENT_MARKS WHERE UPPER(SUBJECT)=UPPER(%s) GROUP BY SUBJECT",
    "pass_count": "SELECT SUBJECT, COUNT(DISTINCT STUDENT_ID) AS STUDENTS_AT_OR_ABOVE_THRESHOLD, %s AS THRESHOLD FROM STUDENT_MARKS WHERE UPPER(SUBJECT)=UPPER(%s) AND MARKS >= %s GROUP BY SUBJECT",
    "marks_for_student": "SELECT STUDENT_ID, STUDENT_NAME, SUBJECT, MARKS FROM STUDENT_MARKS WHERE UPPER(STUDENT_NAME)=UPPER(%s) ORDER BY SUBJECT",
    "all_marks": "SELECT STUDENT_ID, STUDENT_NAME, SUBJECT, MARKS FROM STUDENT_MARKS ORDER BY STUDENT_ID, SUBJECT",
}


def execute_student_question(question: str) -> dict[str, Any]:
    intent = ask_gemma_for_intent(question, STUDENT_PROMPT, STUDENT_ACTIONS)
    action = intent.get("action")
    subject = intent.get("subject")
    student = intent.get("student")
    student2 = intent.get("student2")
    threshold = intent.get("threshold")
    subject = subject.strip() if isinstance(subject, str) and subject.strip() else None
    student = student.strip() if isinstance(student, str) and student.strip() else None
    student2 = student2.strip() if isinstance(student2, str) and student2.strip() else None
    if threshold is not None:
        try:
            threshold = float(threshold)
        except (TypeError, ValueError):
            threshold = None

    if action == "unsupported":
        return {"message": "I can answer questions about student marks. Try averages, highest/lowest marks, comparisons, counts, summaries, or all records."}
    if action in {"average_by_subject", "top_student", "lowest_student", "subject_summary", "pass_count"}:
        if not subject:
            return {"message": "Which subject do you mean: Python or SQL?"}
        if subject.casefold() not in {"python", "sql"}:
            return {"message": f"I don't have marks for '{subject}'. Available subjects: Python and SQL."}
        subject = "Python" if subject.casefold() == "python" else "SQL"
    if action == "marks_for_student" and not student:
        return {"message": "Which student's marks would you like to see?"}
    if action == "compare_students":
        if not student or not student2:
            return {"message": "Please provide both names, for example: Compare Ravi and Meena."}
        if student.casefold() == student2.casefold():
            return {"message": "Please provide two different student names to compare."}
    if action == "pass_count":
        threshold = 35 if threshold is None else threshold
        if threshold < 0 or threshold > 100:
            return {"message": "Please choose a mark threshold between 0 and 100."}
        params = (threshold, subject, threshold)
    elif action in {"average_by_subject", "top_student", "lowest_student", "subject_summary"}:
        params = (subject,)
    elif action == "compare_students":
        params = (student, student2)
    elif action == "marks_for_student":
        params = (student,)
    else:
        params = ()
    sql = STUDENT_SQL[action]
    with get_snowflake_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            columns = [c[0] for c in cur.description]
            rows = cur.fetchall()
    if action == "marks_for_student" and not rows:
        return {"message": f"I couldn't find a student named '{student}'."}
    if action == "compare_students":
        found = {str(row[0]).casefold() for row in rows}
        missing = [n for n in (student, student2) if n.casefold() not in found]
        if missing:
            return {"message": f"I couldn't find: {', '.join(missing)}. Check the names and try again."}
    return {"action": action, "sql": " ".join(sql.split()), "params": list(params), "columns": columns,
            "rows": rows, "subject": subject, "student": student, "student2": student2, "threshold": threshold,
            "dataset": "Student Marks"}


# ---------------- Snowflake TPC-H sample data source ----------------

SAMPLE_ACTIONS = {
    "top_customers", "customer_order_counts", "average_order_value", "total_orders",
    "top_orders", "customers_without_orders", "customer_order_summary", "unsupported",
}

SAMPLE_PROMPT = """ Classify a question for Snowflake's TPC-H SF1 sample data. Do not answer it and do not generate SQL. Return ONLY JSON with keys action and customer. Available tables: CUSTOMER(C_CUSTKEY, C_NAME, C_NATIONKEY, C_ACCTBAL, ...) ORDERS(O_ORDERKEY, O_CUSTKEY, O_ORDERSTATUS, O_TOTALPRICE, O_ORDERDATE, ...) Allowed actions: top_customers, customer_order_counts, average_order_value, total_orders, top_orders, customers_without_orders, customer_order_summary, unsupported. Rules: - top_customers: customers ranked by total order value (join CUSTOMER and ORDERS, sum O_TOTALPRICE, top 10). - customer_order_counts: customers ranked by number of orders (join, count, top 10). - average_order_value: average O_TOTALPRICE across orders. - total_orders: total number of orders. - top_orders: 10 most expensive individual orders with order key, customer key, total price and date. - customers_without_orders: customers with no matching order, using LEFT JOIN; limit 10. - customer_order_summary: summary for a specifically named customer if provided, otherwise unsupported. - unsupported: unrelated questions or a question that does not fit the supported actions. Use customer=null if no single customer name is mentioned. Never invent a customer name or SQL. Examples: Question: Which customers have the highest total order value? {"action":"top_customers","customer":null} Question: How many orders are there? {"action":"total_orders","customer":null} Question: Show customers with no orders {"action":"customers_without_orders","customer":null} Question: Tell me a joke {"action":"unsupported","customer":null} """

SAMPLE_SQL = {
    "top_customers": "SELECT c.C_CUSTKEY, c.C_NAME, COUNT(o.O_ORDERKEY) AS TOTAL_ORDERS, ROUND(SUM(o.O_TOTALPRICE), 2) AS TOTAL_ORDER_VALUE FROM SNOWFLAKE_SAMPLE_DATA.TPCH_SF1.CUSTOMER c JOIN SNOWFLAKE_SAMPLE_DATA.TPCH_SF1.ORDERS o ON c.C_CUSTKEY=o.O_CUSTKEY GROUP BY c.C_CUSTKEY,c.C_NAME ORDER BY TOTAL_ORDER_VALUE DESC LIMIT 10",
    "customer_order_counts": "SELECT c.C_CUSTKEY, c.C_NAME, COUNT(o.O_ORDERKEY) AS TOTAL_ORDERS FROM SNOWFLAKE_SAMPLE_DATA.TPCH_SF1.CUSTOMER c JOIN SNOWFLAKE_SAMPLE_DATA.TPCH_SF1.ORDERS o ON c.C_CUSTKEY=o.O_CUSTKEY GROUP BY c.C_CUSTKEY,c.C_NAME ORDER BY TOTAL_ORDERS DESC,c.C_NAME LIMIT 10",
    "average_order_value": "SELECT ROUND(AVG(O_TOTALPRICE),2) AS AVERAGE_ORDER_VALUE FROM SNOWFLAKE_SAMPLE_DATA.TPCH_SF1.ORDERS",
    "total_orders": "SELECT COUNT(*) AS TOTAL_ORDERS FROM SNOWFLAKE_SAMPLE_DATA.TPCH_SF1.ORDERS",
    "top_orders": "SELECT O_ORDERKEY, O_CUSTKEY, O_TOTALPRICE, O_ORDERDATE FROM SNOWFLAKE_SAMPLE_DATA.TPCH_SF1.ORDERS ORDER BY O_TOTALPRICE DESC LIMIT 10",
    "customers_without_orders": "SELECT c.C_CUSTKEY, c.C_NAME, c.C_ACCTBAL FROM SNOWFLAKE_SAMPLE_DATA.TPCH_SF1.CUSTOMER c LEFT JOIN SNOWFLAKE_SAMPLE_DATA.TPCH_SF1.ORDERS o ON c.C_CUSTKEY=o.O_CUSTKEY WHERE o.O_ORDERKEY IS NULL ORDER BY c.C_CUSTKEY LIMIT 10",
    "customer_order_summary": "SELECT c.C_CUSTKEY, c.C_NAME, COUNT(o.O_ORDERKEY) AS TOTAL_ORDERS, ROUND(COALESCE(SUM(o.O_TOTALPRICE),0),2) AS TOTAL_ORDER_VALUE, ROUND(c.C_ACCTBAL,2) AS ACCOUNT_BALANCE FROM SNOWFLAKE_SAMPLE_DATA.TPCH_SF1.CUSTOMER c LEFT JOIN SNOWFLAKE_SAMPLE_DATA.TPCH_SF1.ORDERS o ON c.C_CUSTKEY=o.O_CUSTKEY WHERE UPPER(c.C_NAME)=UPPER(%s) GROUP BY c.C_CUSTKEY,c.C_NAME,c.C_ACCTBAL",
}


def execute_sample_question(question: str) -> dict[str, Any]:
    intent = ask_gemma_for_intent(
        question, SAMPLE_PROMPT, SAMPLE_ACTIONS
    )

    action = intent.get("action")
    customer = intent.get("customer")
    customer = (
        customer.strip()
        if isinstance(customer, str) and customer.strip()
        else None
    )

    if action == "unsupported":
        return {
            "message": (
                "I couldn't classify this question. "
                "Please try asking in a different way."
            )
        }

    if action == "customer_order_summary" and not customer:
        return {
            "message": "Please provide the exact customer name."
        }

    sql = SAMPLE_SQL.get(action)

    if not sql:
        return {
            "message": "No approved SQL query exists for this question yet."
        }

    params = (customer,) if action == "customer_order_summary" else ()

    with get_snowflake_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            columns = [c[0] for c in cur.description]
            rows = cur.fetchall()

    return {
        "action": action,
        "sql": " ".join(sql.split()),
        "params": list(params),
        "columns": columns,
        "rows": rows,
        "customer": customer,
        "dataset": "Snowflake Sample Data (TPC-H SF1)",
    }

# ---------------- Answer and evidence display ----------------

def display_result(result: dict[str, Any]) -> None:
    if "message" in result:
        st.info(result["message"])
        return
    action, columns, rows = result["action"], result["columns"], result["rows"]
    st.caption(f"Data source: {result.get('dataset', 'Snowflake')}")
    if not rows:
        st.warning("Snowflake returned no matching records for this question.")
    elif action == "average_by_subject":
        st.success(f"Average marks for {rows[0][0]}: {float(rows[0][1]):.2f}")
    elif action == "top_student":
        st.success(f"{rows[0][0]} scored highest in {rows[0][1]} with {rows[0][2]} marks.")
    elif action == "lowest_student":
        st.success(f"{rows[0][0]} scored lowest in {rows[0][1]} with {rows[0][2]} marks.")
    elif action == "compare_subjects":
        averages = {str(row[0]).casefold(): float(row[1]) for row in rows}
        if "python" in averages and "sql" in averages:
            py_avg, sql_avg = averages["python"], averages["sql"]
            if py_avg > sql_avg:
                st.success(f"Python has the higher average: {py_avg:.2f} vs SQL {sql_avg:.2f}.")
            elif sql_avg > py_avg:
                st.success(f"SQL has the higher average: {sql_avg:.2f} vs Python {py_avg:.2f}.")
            else:
                st.success(f"Both subjects have the same average: {py_avg:.2f}.")
        else:
            st.info("Both Python and SQL need records for a fair comparison.")
    elif action == "compare_students":
        st.success(f"Comparison of {result['student']} and {result['student2']}.")
    elif action == "student_count":
        st.success(f"There are {rows[0][0]} distinct students in the database.")
    elif action == "subject_summary":
        row = rows[0]
        st.success(f"{row[0]} summary — average: {float(row[2]):.2f}, lowest: {row[3]}, highest: {row[4]}.")
    elif action == "pass_count":
        st.success(f"{rows[0][1]} student(s) scored at least {rows[0][2]} marks in {rows[0][0]}.")
    elif action == "marks_for_student":
        st.success(f"Found {len(rows)} record(s) for {rows[0][1]}.")
    elif action == "all_marks":
        st.success(f"Retrieved {len(rows)} student mark record(s) from Snowflake.")
    elif action == "top_customers":
        st.success("Top 10 customers ranked by total order value.")
    elif action == "customer_order_counts":
        st.success("Top 10 customers ranked by number of orders.")
    elif action == "average_order_value":
        st.success(f"Average order value: {float(rows[0][0]):,.2f}")
    elif action == "total_orders":
        st.success(f"Total orders in the sample data: {rows[0][0]:,}")
    elif action == "top_orders":
        st.success("The 10 most expensive individual orders are shown below.")
    elif action == "customers_without_orders":
        st.success(f"Found {len(rows)} customer(s) without a matching order in this result (maximum 10 shown).")
    elif action == "customer_order_summary":
        row = rows[0]
        st.success(f"Customer {row[1]} has {row[2]:,} orders with total order value {float(row[3]):,.2f}.")

    if rows:
        st.subheader("📋 Database evidence")
        st.dataframe([dict(zip(columns, row)) for row in rows], use_container_width=True, hide_index=True)
        if action in {"top_customers", "customer_order_counts", "top_orders"}:
            numeric = [c for c in columns if c in {"TOTAL_ORDER_VALUE", "TOTAL_ORDERS", "O_TOTALPRICE"}]
            label_col = "C_NAME" if "C_NAME" in columns else ("O_ORDERKEY" if "O_ORDERKEY" in columns else None)
            if numeric and label_col:
                chart_data = {label_col: [str(r[columns.index(label_col)]) for r in rows], numeric[0]: [float(r[columns.index(numeric[0])]) for r in rows]}
                st.subheader("📊 Visual summary")
                st.bar_chart(chart_data, x=label_col, y=numeric[0])

    with st.expander("🔍 Inspect SQL query and evidence"):
        st.markdown("**SQL query executed**")
        st.code(result["sql"], language="sql")
        st.markdown("**Bound query parameters**")
        st.json(result["params"] if result["params"] else [])
        st.markdown("**Rows returned by Snowflake**")
        st.write(f"{len(rows)} row(s)")
        if rows:
            st.dataframe([dict(zip(columns, row)) for row in rows], use_container_width=True, hide_index=True)
    st.caption("Snowflake computed the result. Gemma interpreted the question; the displayed rows are the evidence.")


# ---------------- Sidebar and main interaction ----------------

with st.sidebar:
    st.header("Choose your dataset")
    dataset = st.radio(
        "Data source",
        ["Student Marks", "Snowflake Sample Data (TPC-H SF1)"],
        index=0,
        help="Select which Snowflake dataset DataMind should query.",
    )
    st.divider()
    if dataset == "Student Marks":
        st.subheader("Try a question")
        st.markdown(
            "- What is the average mark for Python?\n"
            "- Who scored highest in SQL?\n"
            "- Who scored lowest in Python?\n"
            "- Which subject has the higher average?\n"
            "- Compare Ravi and Meena\n"
            "- How many students are there?\n"
            "- Show the marks summary for SQL\n"
            "- How many students scored at least 35 in Python?\n"
            "- Show all student marks"
        )
        placeholder = "Which subject has the higher average?"
        help_text = "Ask about Python/SQL marks, students, averages, comparisons, or summaries."
    else:
        st.subheader("Try a question")
        st.markdown(
            "- Which customers have the highest total order value?\n"
            "- Which customers have the most orders?\n"
            "- What is the average order value?\n"
            "- How many orders are there?\n"
            "- Show the 10 most expensive orders\n"
            "- Show customers without orders\n"
            "- Show the order summary for customer [exact name]"
        )
        placeholder = "Which customers have the highest total order value?"
        help_text = "Ask about customer rankings, order counts, average value, or order records."
    st.divider()
    st.caption("Gemma interprets the question. Approved SQL templates retrieve the data.")

st.markdown(f"**Selected dataset:** {dataset}")
question = st.text_input("Ask a question", placeholder=placeholder, help=help_text)
if st.button("Ask DataMind", type="primary", use_container_width=True):
    if not question.strip():
        st.warning("Please enter a question first.")
    else:
        try:
            with st.spinner("Gemma is interpreting your question and querying Snowflake..."):
                if dataset == "Student Marks":
                    result = execute_student_question(question.strip())
                else:
                    result = execute_sample_question(question.strip())
            display_result(result)
        except json.JSONDecodeError:
            st.error("Gemma returned a response that could not be read. Please try again.")
        except KeyError as error:
            st.error(f"A required configuration value is missing: {error}. Check .streamlit/secrets.toml.")
        except Exception as error:
            st.error("DataMind couldn't complete the request. Check Snowflake permissions, connection, and Gemma settings.")
            with st.expander("Technical details"):
                st.code(f"{type(error).__name__}: {error}")

st.divider()
st.caption("DataMind • Google Gemma + Snowflake • Inspectable SQL and evidence")