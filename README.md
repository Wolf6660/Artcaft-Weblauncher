# Artcraft Weblauncher

**Aktuelle Version: [0.5](https://github.com/Wolf6660/Artcaft-Weblauncher/tree/v0.5)**

Weblauncher für die [Craft-Anwendungen von storytold](https://github.com/orgs/storytold/repositories?type=all) und [SolidCraft](https://github.com/tangency-labs/solidcraft). Anwendungen im Browser installieren, starten und einzeln oder gemeinsam aktualisieren. Für Synology Container Manager und Linux mit Docker Compose V2, auf AMD64 und ARM64.

Unabhängiges Projekt; kein offizielles Produkt der Softwarehersteller.

## Installation

Einen Projektordner mit den Unterordnern `public` und `data` anlegen. Die folgenden Dateien `compose.yaml` und `.env` darin speichern. Auf Synology anschließend unter **Container Manager → Projekt → Erstellen** dieses Verzeichnis und die YAML auswählen und das Projekt starten.

**`compose.yaml`:**

```yaml
services:
  artcraft:
    image: ghcr.io/wolf6660/artcaft-weblauncher:latest
    pull_policy: always
    container_name: artcraft
    restart: unless-stopped
    ports:
      - "${ARTCRAFT_PORT:-31000}:8080"
    environment:
      TZ: Europe/Berlin
      CHECK_INTERVAL_HOURS: "12"
      ADMIN_PASSWORD: "${ADMIN_PASSWORD:-}"
      GITHUB_TOKEN: "${GITHUB_TOKEN:-}"
    volumes:
      - ./public:/public:ro
      - ./data:/data
    security_opt:
      - no-new-privileges:true
```

**`.env` im gleichen Verzeichnis:**

```dotenv
ARTCRAFT_PORT=31000
ADMIN_PASSWORD=
GITHUB_TOKEN=
```

`ADMIN_PASSWORD` ist optional; der Benutzername lautet `admin`. `GITHUB_TOKEN` ist ebenfalls optional und erhöht das GitHub-API-Limit, etwa bei häufigen Update-Prüfungen. Einen [persönlichen Token erstellen](https://github.com/settings/tokens/new), für öffentliche Informationen keine Scopes auswählen und den Wert ausschließlich in die lokale `.env` eintragen.

Alternativ zum Container Manager im Projektordner ausführen:

```sh
docker compose up -d
```

Danach **`http://SERVER-IP:31000`** öffnen. Zum Aktualisieren des Launchers das Projekt neu erstellen oder `docker compose pull` und anschließend `docker compose up -d --force-recreate` ausführen. Vorhandene Ordner `public`, `data` und die persönliche `.env` behalten.
