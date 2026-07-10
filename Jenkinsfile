pipeline {
    agent any

    stages {
        stage('1. Checkout') {
            steps {
                checkout scm
            }
        }

        stage('2. Prepare Python Virtualenv') {
            steps {
                echo 'Creating Python Virtual Environment...'
                // 젠킨스 빌드 격리를 위해 로컬 venv를 생성하고 필수 모듈 설치
                sh '''
                python3 -m venv venv
                . venv/bin/activate
                pip install --upgrade pip
                pip install pyinstaller pillow
                '''
            }
        }

        stage('3. Build Comic Viewer') {
            steps {
                echo 'Building Comic Viewer...'
                sh '''
                . venv/bin/activate
                pyinstaller --noconfirm ComicViewer.spec
                '''
            }
        }

        stage('4. Build Comic Downloader') {
            steps {
                echo 'Building Comic Downloader...'
                sh '''
                . venv/bin/activate
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
