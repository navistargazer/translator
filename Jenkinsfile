pipeline {
    agent any

    environment {
        // 로컬 Conda 환경의 python 및 pyinstaller를 참조할 수 있도록 PATH 환경 변수 추가
        PATH = "/home/jang/miniconda3/envs/comic_env/bin:${env.PATH}"
    }

    stages {
        stage('1. Checkout') {
            steps {
                checkout scm
            }
        }

        stage('2. Build Comic Viewer') {
            steps {
                echo 'Building Comic Viewer...'
                // PyInstaller 빌드 수행
                sh 'pyinstaller --noconfirm ComicViewer.spec'
            }
        }

        stage('3. Build Comic Downloader') {
            steps {
                echo 'Building Comic Downloader...'
                // ComicDownloader.spec 파일이 존재하는 경우에만 선택적 빌드 구동
                sh '''
                if [ -f ComicDownloader.spec ]; then
                    pyinstaller --noconfirm ComicDownloader.spec
                else
                    echo "ComicDownloader.spec not found, skipping."
                fi
                '''
            }
        }

        stage('4. Archive Artifacts') {
            steps {
                echo 'Archiving build artifacts...'
                // 빌드 완료된 dist 폴더 내의 실행 파일들을 젠킨스 서버에 백업 저장
                archiveArtifacts artifacts: 'dist/**/*', onlyIfSuccessful: true
            }
        }
    }
}
