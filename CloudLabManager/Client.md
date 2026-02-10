Go to [[Introduction]]

See [[Frontend]] for the full documentation of the browser-based client.

The client is a vanilla HTML/CSS/JS single-page application served by FastAPI at `http://localhost:8000`. No build step required.

## Usage Flow

1. Open `http://localhost:8000`
2. First boot: complete [[Authentication#First-Time Setup|setup]] (create admin + vault password)
3. Login with your credentials
4. Use the dashboard to monitor jobs and manage infrastructure
5. Navigate to **Services** to deploy CloudLab services
6. Navigate to **Instances** to view running Vultr VMs
7. Navigate to **Jobs** to see deployment history and live output
