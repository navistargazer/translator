pipeline {
    agent {
        docker {
            image 'python:3.12-slim'
        }
    }

    stages {
        stage('1. Checkout') {
            steps {
                checkout scm
            }
        }

        stage('2. Install Build Dependencies') {
            steps {
                echo 'Installing PyInstaller and Pillow inside build container...'
                sh 'pip install --no-cache-dir pyinstaller pillow'
            }
        }

        stage('3. Build Comic Viewer') {
            steps {
                echo 'Building Comic Viewer...'
                sh 'pyinstaller --noconfirm ComicViewer.spec'
            }
        }

        stage('4. Build Comic Downloader') {
            steps {
                echo 'Building Comic Downloader...'
                sh '''
                if [ -f ComicDownloader.spec ]; then
                    pyinstaller --noconfirm ComicDownloader.spec
                else
                    echo "ComicDownloader.spec not found, skipping."
                fi
                '''
            }
        }

        stage('5. Archive Artifacts') {
            steps {
                echo 'Archiving build artifacts...'
                archiveArtifacts artifacts: 'dist/**/*', onlyIfSuccessful: true
            }
        }
    }
}
