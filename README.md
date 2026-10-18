Problem Statement

Build an explainable natural-language data assistant that lets users ask questions about real datasets and receive accurate answers grounded in actual query results, with inspectable SQL queries and supporting source rows.

DataMind — Talk to Your Data

DataMind is a natural-language data assistant that uses Snowflake to query real data and Google Gemma to interpret user questions.

Current Progress

- Created a Snowflake database and schema.
- Created the "STUDENT_MARKS" table and inserted six sample records.
- Connected Python to Snowflake and retrieved the student records.
- Set up the Python environment for the application.

Technology Stack

- Python
- Snowflake SQL
- Google Gemma
- Streamlit

Planned Features

- Ask questions about data using natural language.
- Execute approved SQL queries against Snowflake.
- Display answers supported by actual query results.
- Show the SQL query and supporting rows for explainability.
- Handle unsupported or ambiguous questions clearly.
