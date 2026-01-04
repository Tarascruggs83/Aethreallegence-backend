import json
import os
import pymysql

conn = None

def get_connection():
    global conn
    if conn is None or not conn.open:
        conn = pymysql.connect(
            host=os.environ["DB_HOST"],
            port=int(os.environ.get("DB_PORT", "3306")),
            user=os.environ["DB_USER"],
            password=os.environ["DB_PASSWORD"],
            db=os.environ["DB_NAME"],
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=False,
            connect_timeout=5,
            read_timeout=10,
            write_timeout=10,
        )
    return conn

def parse_body(event):
    # event may be None / not a dict in weird tests
    if not isinstance(event, dict):
        return {}

    body = event.get("body")

    # 1) Missing body
    if body is None:
        return {}

    # 2) API Gateway usually sends a JSON string
    if isinstance(body, str):
        body = body.strip()
        if not body:
            return {}
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            # body wasn't valid JSON
            return {}

    # 3) Lambda console test sometimes uses dict body
    if isinstance(body, dict):
        return body

    # 4) Anything else
    return {}

def lambda_handler(event, context):
    print("EVENT:", json.dumps(event))

    body = parse_body(event)
    print("BODY:", body)
    # if isinstance(body, str):
    #     body = json.loads(body or "{}")

    product_name = body.get("product_name")
    location = body.get("location")
    event_type = body.get("event")
    print("PRODUCT:", product_name)

    if not product_name or not location or not event_type:
        return {
            "statusCode": 400,
            "body": json.dumps({"message": "product_name, location and event are required"})
        }

    conn = get_connection()

    try:
        with conn.cursor() as cur:
            # 1) Check if product exists
            cur.execute("SELECT id FROM products WHERE label = %s", (product_name))
            row = cur.fetchone()

            if row:
                product_id = row["id"]
            else:
                # 2) Insert product if it doesn't exist
                try:
                    cur.execute(
                        "INSERT INTO products (label) VALUES (%s)",
                        (product_name)
                    )
                    product_id = cur.lastrowid
                except pymysql.err.IntegrityError:
                    # Race condition: another request inserted the same product name
                    cur.execute("SELECT id FROM products WHERE label = %s", (product_name))
                    row = cur.fetchone()
                    if not row:
                        raise  # something else went wrong
                    product_id = row["id"]

            # 3) Insert event (always)
            cur.execute(
                """
                INSERT INTO events (product_id, zone_from,zone_to, event_type)
                VALUES (%s, %s,%s, %s)
                """,
                (product_id, 1,2, event_type)
            )
            event_id = cur.lastrowid

        conn.commit()

        return {
            "statusCode": 200,
            "body": json.dumps({
                "product_id": product_id,
                "event_id": event_id
            })
        }

    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass

        print("Error:", str(e))
        return {
            "statusCode": 500,
            "body": json.dumps({"message": "Internal server error"})
        }
