import pymysql

connection = pymysql.connect(host='localhost',
                             user='root',
                             password='2005',
                             database='minimart')
try:
    with connection.cursor() as cursor:
        cursor.execute("ALTER TABLE user ADD COLUMN is_verified BOOLEAN DEFAULT FALSE;")
        cursor.execute("ALTER TABLE user ADD COLUMN otp VARCHAR(6);")
        cursor.execute("ALTER TABLE user ADD COLUMN otp_expiry DATETIME;")
        connection.commit()
    print("Database updated successfully.")
except pymysql.err.OperationalError as e:
    # 1060 is Duplicate column name error
    if e.args[0] == 1060:
        print("Columns already exist. Skipping.")
    else:
        print(f"Error: {e}")
finally:
    connection.close()
