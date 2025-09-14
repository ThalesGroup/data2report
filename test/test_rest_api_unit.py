from rest import app


class TestRestAppErrors:
    def test_verify_sql_method_not_allowed(self):
        result = app.test_client().post("/ping")
        assert result.status_code == 405


class TestRestApp:

    def test_pint(self):
        result = app.test_client().get("/ping")
        assert result.status_code == 200
