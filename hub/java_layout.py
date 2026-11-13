"""Maven and Gradle layouts for new Java projects."""
import re


SISTEMAS_JAVA = {
    'None': 'Plain .java files in src. Run them with the Run button; nothing to download.',
    'Maven': 'pom.xml and src/main/java. The usual choice in courses and companies; libraries come from Maven Central.',
    'Gradle': 'build.gradle and src/main/java. Used by Android and many Spring projects; downloads Gradle the first time.',
}
POM = '''<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 https://maven.apache.org/xsd/maven-4.0.0.xsd">
    <modelVersion>4.0.0</modelVersion>
    <groupId>org.example</groupId>
    <artifactId>{nome}</artifactId>
    <version>1.0-SNAPSHOT</version>
    <properties>
        <maven.compiler.release>21</maven.compiler.release>
        <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>
    </properties>
</project>
'''
GRADLE = '''plugins {{
    id 'application'
}}

repositories {{
    mavenCentral()
}}

java {{
    toolchain {{
        languageVersion = JavaLanguageVersion.of(21)
    }}
}}

application {{
    mainClass = 'Main'
}}
'''


def montar_java(raiz, sistema, nome):
    """Turns a plain src/ project into Maven or Gradle layout; the Java extension imports either."""
    if sistema not in ('Maven', 'Gradle'):
        return
    destino = raiz / 'src/main/java'
    destino.mkdir(parents=True, exist_ok=True)
    for f in list((raiz / 'src').glob('*.java')):
        f.replace(destino / f.name)
    artefato = re.sub(r'[^a-z0-9-]+', '-', nome.lower()).strip('-') or 'app'
    if sistema == 'Maven':
        (raiz / 'pom.xml').write_text(POM.replace('{nome}', artefato), encoding='utf8')
        ignorar = ['target/']
    else:
        (raiz / 'build.gradle').write_text(GRADLE.format(), encoding='utf8')
        (raiz / 'settings.gradle').write_text(f"rootProject.name = '{artefato}'\n", encoding='utf8')
        ignorar = ['build/', '.gradle/']
    arquivo = raiz / '.gitignore'
    linhas_ = arquivo.read_text(encoding='utf8').splitlines() if arquivo.exists() else []
    arquivo.write_text('\n'.join([*linhas_, *[i for i in ignorar if i not in linhas_]]) + '\n', encoding='utf8')
