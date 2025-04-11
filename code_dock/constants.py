"""
constants.py - 全局常量定义
包含代码库搜索系统中使用的所有常量定义
"""

# 排除目录列表
BLACKLIST_DIR = [
    "__pycache__", ".pytest_cache", ".venv", ".git", ".idea", 
    "venv", "env", "node_modules", "dist", "build", ".vscode", 
    ".github", ".gitlab", ".angular", "cdk.out", ".aws-sam", ".terraform",
    "__MACOSX", "other"
]

# 允许处理的文件扩展名
WHITELIST_FILES = [
    # 代码文件扩展名
    ".java", ".py", ".js", ".rs", ".c", ".cpp", ".cs", ".php", ".rb", ".go", ".ts", ".jsx", ".tsx", ".h", ".hpp", ".swift", ".kt", ".scala", ".dart", ".groovy", ".pl", ".sh", ".bat", ".ps1", ".lua",
    # 配置文件扩展名
    ".json", ".xml", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".conf", ".properties", ".props", ".env", ".config", ".lock",
    # 特定配置文件名
    "build.gradle", "go.mod", "Gemfile", ".sln", ".txt", "Makefile", ".git", ".gitignore", ".md",
    # 前端/Web配置文件
    "package.json", "package-lock.json", "yarn.lock", ".npmrc", ".babelrc", "webpack.config.js", "tsconfig.json", ".eslintrc", ".prettierrc", ".stylelintrc", "angular.json", "vue.config.js", "next.config.js", "nuxt.config.js",
    # 后端/服务器配置文件
    "requirements.txt", "setup.py", "settings.py", "pom.xml", "build.sbt", "application.properties", "application.yml", "web.config", ".htaccess", "Pipfile", "composer.json", "build.xml",
    # 容器/CI/CD配置文件
    "Dockerfile", "docker-compose.yml", ".dockerignore", "Jenkinsfile", ".gitlab-ci.yml", ".travis.yml", ".github/workflows", ".circleci", "azure-pipelines.yml",
    # 其他工具配置文件
    ".editorconfig", ".vscode", ".idea", ".project", ".classpath", "CMakeLists.txt", "configure.ac", "Makefile.am", ".hgignore", "sonar-project.properties", "manifest.json", "App.config", "Web.config", "appsettings.json"
]


# 明确排除的文件
BLACKLIST_FILES = ["docker-compose.yml", ".DS_Store"]


# 引用标识符
REFERENCE_IDENTIFIERS = {
    "python": {
        "class": "identifier",
        "method": "call",
        "child_field_name": "function"
    },
    "java": {
        "class": "identifier",
        "method": "method_invocation",
        "child_field_name": "name"
    },
    "javascript": {
        "class": "identifier",
        "method": "call_expression",
        "child_field_name": "function"
    },
    "rust": {
        "class": "identifier",
        "method": "call_expression",
        "child_field_name": "function"
    }
}

STRONG_SEARCH_SUPPORTED_LANGUAGES = {
        "java": (".java",),
        "python": (".py",),
        "typescript": (".ts", ".tsx"),
        "javascript": (".js", ".jsx"),
        "csharp": (".cs",),
        "go": (".go",),
        "rust": (".rs",),
        "kotlin": (".kt", ".kts"),
        "ruby": (".rb",),
        "dart": (".dart",)
}

# 可识别代码库的文件列表 (从api.py)
RECOGNIZABLE_FILES = [
    "package.json",        # Node.js
    "requirements.txt",    # Python
    "setup.py",            # Python
    "pom.xml",             # Java (Maven)
    "build.gradle",        # Java/Kotlin (Gradle)
    "Cargo.toml",          # Rust
    "go.mod",              # Go
    "Gemfile",             # Ruby
    "composer.json",       # PHP
    ".sln",                # C#/.NET
    "CMakeLists.txt",      # C/C++
    "Makefile",            # General
    ".git",                # Git repository
    ".gitignore",          # Git configuration
    "README.md",           # Documentation
    "*.py",                # Python files
    "*.java",              # Java files
    "*.js",                # JavaScript files
    "*.ts",                # TypeScript files
    "*.go",                # Go files
    "*.rs",                # Rust files
    "*.c",                 # C files
    "*.cpp",               # C++ files
    "*.cs",                # C# files
    "*.php",               # PHP files
    "*.rb",                # Ruby files
] 