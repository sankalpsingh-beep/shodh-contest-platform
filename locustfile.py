from locust import HttpUser, task, between

class ShodhUser(HttpUser):
    wait_time = between(1, 2)

    def on_start(self):
        response = self.client.post(
            "/auth/token",
            json={
                "email": "participant1@shodh.dev",
                "password": "ShodhDemo@2026"
            }
        )

        if response.status_code == 200:
            token = response.json()["access_token"]
            self.headers = {"Authorization": f"Bearer {token}"}
        else:
            self.headers = {}

    @task(3)
    def list_contests(self):
        self.client.get(
            "/organizations/753ec31f-4878-48e8-b669-34e06b488810/contests",
            headers=self.headers
        )

    @task(2)
    def get_contest(self):
        self.client.get(
            "/contests/7ca875af-632f-4183-be41-fc585b3eee67",
            headers=self.headers
        )

    @task(2)
    def leaderboard(self):
        self.client.get(
            "/contests/7ca875af-632f-4183-be41-fc585b3eee67/leaderboard",
            headers=self.headers
        )

    @task(1)
    def list_problems(self):
        self.client.get(
            "/contests/7ca875af-632f-4183-be41-fc585b3eee67/problems",
            headers=self.headers
        )
