"""AutoTask 3.0 - consultas distribuídas PostgreSQL / Oracle XE com autenticação."""







import csv



import io



import json



import os



import re



import time



import uuid







from concurrent.futures import ThreadPoolExecutor, as_completed



from functools import wraps







from flask import (



    Flask,



    jsonify,



    redirect,



    render_template,



    request,



    send_file,



    session,



    url_for,



)







from openpyxl import Workbook



from werkzeug.security import check_password_hash, generate_password_hash











# ============================================================



# CONFIGURAÇÃO



# ============================================================







BASE = os.path.dirname(os.path.abspath(__file__))







CFG = json.load(



    open(



        os.path.join(BASE, "config.json"),



        encoding="utf-8"



    )



)







LOJAS = {



    int(loja["loja"]): loja["host"]



    for loja in json.load(



        open(



            os.path.join(BASE, "lojas.json"),



            encoding="utf-8"



        )



    )



}







MAX_PARALELO = CFG.get("max_paralelo", 20)



TIMEOUT_S = CFG.get("timeout_segundos", 30)



MAX_LINHAS_LOJA = CFG.get("max_linhas_por_loja", 5000)



MAX_LINHAS_TELA = 2000



# ============================================================

# ORACLE CLIENT - THICK MODE

# Opcional: necessário apenas quando o ambiente Oracle exigir modo Thick.

# ============================================================



import oracledb



ORACLE_CLIENT_DIR = CFG.get(

    "oracle",

    {}

).get(

    "client_dir",

    r"C:\oracle\product\instantclient_21_15"

)



if ORACLE_CLIENT_DIR and os.path.isdir(ORACLE_CLIENT_DIR):
    try:
        oracledb.init_oracle_client(lib_dir=ORACLE_CLIENT_DIR)
    except Exception as exc:
        print(f"[AVISO] Oracle Thick não iniciado: {exc}")









RESULTADOS = {}











# ============================================================



# FLASK



# ============================================================







app = Flask(__name__)







app.secret_key = os.environ.get(



    "AUTOTASK_SECRET_KEY",



    "autotask-3-troque-esta-chave"



)







app.config.update(



    SESSION_COOKIE_HTTPONLY=True,



    SESSION_COOKIE_SAMESITE="Lax",



)











# ============================================================



# USUÁRIOS



# ============================================================







ARQUIVO_USUARIOS = os.path.join(



    BASE,



    "usuarios.json"



)







USUARIOS_INICIAIS = {
    os.environ.get("AUTOTASK_USER", "admin"): {
        "senha": os.environ.get("AUTOTASK_PASSWORD", "troque-esta-senha"),
        "perfil": "admin"
    }
}


# ============================================================



# SINCRONIZAR USUÁRIOS



# ============================================================







def sincronizar_usuarios():







    usuarios = {}







    if os.path.exists(ARQUIVO_USUARIOS):







        try:







            with open(



                ARQUIVO_USUARIOS,



                "r",



                encoding="utf-8"



            ) as arquivo:







                usuarios = json.load(



                    arquivo



                )







        except (



            json.JSONDecodeError,



            OSError



        ):







            usuarios = {}







    alterado = False







    for usuario, dados in USUARIOS_INICIAIS.items():







        if usuario not in usuarios:







            usuarios[usuario] = {







                "senha_hash": generate_password_hash(



                    dados["senha"]



                ),







                "perfil": dados["perfil"],







                "ativo": True



            }







            alterado = True







    if (



        alterado



        or



        not os.path.exists(ARQUIVO_USUARIOS)



    ):







        with open(



            ARQUIVO_USUARIOS,



            "w",



            encoding="utf-8"



        ) as arquivo:







            json.dump(



                usuarios,



                arquivo,



                indent=4,



                ensure_ascii=False



            )











def carregar_usuarios():







    sincronizar_usuarios()







    with open(



        ARQUIVO_USUARIOS,



        "r",



        encoding="utf-8"



    ) as arquivo:







        return json.load(



            arquivo



        )











sincronizar_usuarios()











# ============================================================



# PROTEÇÃO DAS ROTAS



# ============================================================







def login_required(view):







    @wraps(view)



    def wrapped(*args, **kwargs):







        if not session.get("autenticado"):







            if request.path.startswith("/api/"):







                return jsonify(



                    erro="Sessão expirada. Faça login novamente."



                ), 401







            return redirect(



                url_for("login")



            )







        return view(



            *args,



            **kwargs



        )







    return wrapped











# ============================================================



# LOGIN



# ============================================================







@app.route(



    "/login",



    methods=[



        "GET",



        "POST"



    ]



)



def login():







    if session.get("autenticado"):







        return redirect(



            url_for("index")



        )







    erro = None







    if request.method == "POST":







        usuario = request.form.get(



            "usuario",



            ""



        ).strip()







        senha = request.form.get(



            "senha",



            ""



        )







        usuarios = carregar_usuarios()







        dados_usuario = usuarios.get(



            usuario



        )







        if dados_usuario:







            usuario_ativo = dados_usuario.get(



                "ativo",



                False



            )







            senha_hash = dados_usuario.get(



                "senha_hash",



                ""



            )







            senha_correta = (



                bool(senha_hash)



                and



                check_password_hash(



                    senha_hash,



                    senha



                )



            )







            if (



                usuario_ativo



                and



                senha_correta



            ):







                session.clear()







                session["autenticado"] = True







                session["usuario"] = usuario







                session["perfil"] = dados_usuario.get(



                    "perfil",



                    "usuario"



                )







                return redirect(



                    url_for("index")



                )







        erro = "Usuário ou senha inválidos."







    return render_template(



        "login.html",



        erro=erro



    )











# ============================================================



# LOGOUT



# ============================================================







@app.get("/logout")



def logout():







    session.clear()







    return redirect(



        url_for("login")



    )











# ============================================================



# SEGURANÇA SQL



# ============================================================







PROIBIDAS = re.compile(



    r"\b("



    r"insert|update|delete|drop|alter|truncate|create|"



    r"grant|revoke|merge|call|exec|execute|copy|into|"



    r"lock|vacuum"



    r")\b",



    re.I



)











def validar_sql(sql: str) -> str:







    sql = (



        sql or ""



    ).strip()







    if not sql:







        raise ValueError(



            "Informe a consulta SQL."



        )







    if sql.endswith(";"):







        raise ValueError(



            "Remova o ponto e vírgula final."



        )







    sql_sem_strings = re.sub(



        r"'[^']*'|\"[^\"]*\"",



        "",



        sql



    )







    if ";" in sql_sem_strings:







        raise ValueError(



            "Envie apenas uma instrução por vez."



        )







    if not re.match(



        r"^(select|with)\b",



        sql,



        re.I



    ):







        raise ValueError(



            "Modo somente leitura: apenas SELECT e WITH."



        )







    proibida = PROIBIDAS.search(



        sql_sem_strings



    )







    if proibida:







        raise ValueError(



            "Palavra não permitida em modo somente leitura: "



            f"{proibida.group(0).upper()}"



        )







    return sql











# ============================================================



# CONSULTA POR LOJA



# ============================================================







def consultar_loja(



    banco: str,



    loja: int,



    host: str,



    sql: str



):







    # ========================================================



    # POSTGRESQL



    # ========================================================







    if banco == "postgres":







        import psycopg2







        config = CFG[



            "postgres"



        ]







        conn = psycopg2.connect(







            host=host,







            port=config.get(



                "porta",



                5432



            ),







            dbname=config[



                "banco"



            ],







            user=config[



                "usuario"



            ],







            # Usa diretamente a senha do config.json



            password=config[



                "senha"



            ],







            connect_timeout=10,







            options=(



                f"-c statement_timeout={TIMEOUT_S ** 1000} "



                "-c default_transaction_read_only=on"



            )



        )







        try:







            with conn.cursor() as cursor:







                cursor.execute(



                    sql



                )







                colunas = [



                    descricao[0]



                    for descricao



                    in cursor.description



                ]







                linhas = cursor.fetchmany(



                    MAX_LINHAS_LOJA



                )







                return (



                    colunas,



                    linhas



                )







        finally:







            conn.close()











        # ========================================================



    # ORACLE



    # ========================================================







    elif banco == "oracle":







        import oracledb







        config = CFG[



            "oracle"



        ]







        # ====================================================



        # MONTA O DSN DO ORACLE XE USANDO SID



        #



        # Exemplo de instância:



        #



        # HOST: db110.example.local



        # PORTA: 1521



        # SID: xe



        # ====================================================







        dsn = oracledb.makedsn(



            host,



            config.get(



                "porta",



                1521



            ),



            sid=config.get(



                "sid",



                "xe"



            )



        )







        conn = oracledb.connect(







            user=config[



                "usuario"



            ],







            # Usa diretamente a senha do config.json



            password=config[



                "senha"



            ],







            dsn=dsn,







            tcp_connect_timeout=10



        )







        try:







            conn.call_timeout = (



                TIMEOUT_S



                *



                1000



            )







            cursor = conn.cursor()







            # Oracle em modo somente leitura



            cursor.execute(



                "SET TRANSACTION READ ONLY"



            )







            cursor.execute(



                sql



            )







            colunas = [



                descricao[0]



                for descricao



                in cursor.description



            ]







            linhas = cursor.fetchmany(



                MAX_LINHAS_LOJA



            )







            return (



                colunas,



                linhas



            )







        finally:







            conn.close()











# ============================================================



# PÁGINA PRINCIPAL



# ============================================================







@app.get("/")



@login_required



def index():







    return render_template(







        "index.html",







        total_lojas=len(



            LOJAS



        ),







        usuario=session.get(



            "usuario",



            ""



        ),







        perfil=session.get(



            "perfil",



            "usuario"



        )



    )











# ============================================================



# API - CONSULTAR



# ============================================================







@app.post(



    "/api/consultar"



)



@login_required



def api_consultar():







    dados = request.get_json(



        force=True



    )







    banco = dados.get(



        "banco",



        "postgres"



    )







    if banco not in (



        "postgres",



        "oracle"



    ):







        return jsonify(



            erro="Banco inválido."



        ), 400











    # ========================================================



    # VALIDAR SQL



    # ========================================================







    try:







        sql = validar_sql(



            dados.get(



                "sql"



            )



        )







    except ValueError as erro:







        return jsonify(



            erro=str(



                erro



            )



        ), 400











    # ========================================================



    # DEFINIR LOJAS



    # ========================================================







    if dados.get(



        "escopo"



    ) == "rede":







        # O escopo completo usa a lista de instâncias definida em lojas.json.



        alvo = sorted(



            LOJAS.items()



        )







    else:







        # ====================================================



        # LOJAS ESPECÍFICAS



        # ====================================================



        #



        # Exemplo:



        #



        # 110, 255



        #



        # gera:



        #



        # db110.example.local



        # db255.example.local



        #



        # ====================================================







        pedidas = {







            int(numero)







            for numero in re.findall(



                r"\d+",







                dados.get(



                    "lojas",



                    ""



                )



            )



        }







        if not pedidas:







            return jsonify(



                erro=(



                    "Informe ao menos uma loja "



                    "(ex.: 110, 255)."



                )



            ), 400











        alvo = []







        for filial in sorted(



            pedidas



        ):







            # =================================================



            # GERA O HOST AUTOMATICAMENTE



            # =================================================







            host = f"db{filial:03d}.example.local"







            alvo.append(



                (



                    filial,



                    host



                )



            )











    # ========================================================



    # EXECUTAR



    # ========================================================







    inicio = time.time()







    colunas = None







    linhas = []







    erros = []







    sucesso = 0











    # ========================================================



    # EXECUTAR CONSULTAS EM PARALELO



    # ========================================================







    with ThreadPoolExecutor(



        max_workers=MAX_PARALELO



    ) as executor:







        tarefas = {







            executor.submit(



                consultar_loja,



                banco,



                loja,



                host,



                sql



            ): (



                loja,



                host



            )







            for loja, host



            in alvo



        }











        for tarefa in as_completed(



            tarefas



        ):







            loja, host = tarefas[



                tarefa



            ]







            try:







                cols, rows = (



                    tarefa.result()



                )







                colunas = (



                    colunas



                    or



                    cols



                )







                sucesso += 1







                linhas.extend(







                    [



                        loja,



                        host,



                        *row



                    ]







                    for row



                    in rows



                )







            except Exception as erro:







                erros.append(



                    {







                        "loja":



                            loja,







                        "host":



                            host,







                        "erro": (



                            str(



                                erro



                            )



                            .strip()



                            .splitlines()[0][:300]



                        )







                    }



                )











    # ========================================================



    # ORGANIZAR RESULTADOS



    # ========================================================







    linhas.sort(



        key=lambda row:



            row[0]



    )











    colunas = [







        "LOJA",







        "HOST",







        *(



            coluna.upper()







            for coluna



            in (



                colunas



                or



                []



            )



        )



    ]











    # ========================================================



    # ID DO RESULTADO



    # ========================================================







    resultado_id = (



        uuid.uuid4().hex



    )











    RESULTADOS[



        resultado_id



    ] = {







        "colunas":



            colunas,







        "linhas":



            linhas



    }











    # Mantém somente os últimos 20 resultados.



    while len(



        RESULTADOS



    ) > 20:







        RESULTADOS.pop(







            next(



                iter(



                    RESULTADOS



                )



            )



        )











    # ========================================================



    # RETORNO



    # ========================================================







    return jsonify(







        id=resultado_id,







        lojas=len(



            alvo



        ),







        sucesso=sucesso,







        erros=sorted(







            erros,







            key=lambda erro:



                erro[



                    "loja"



                ]



        ),







        linhas=len(



            linhas



        ),







        tempo=round(



            time.time()



            -



            inicio,



            1



        ),







        colunas=colunas,







        dados=[







            [







                (



                    ""







                    if valor is None







                    else str(



                        valor



                    )



                )







                for valor



                in linha



            ]







            for linha



            in linhas[



                :MAX_LINHAS_TELA



            ]



        ]



    )











# ============================================================



# DOWNLOAD



# ============================================================







@app.get(



    "/api/download/<rid>.<fmt>"



)



@login_required



def api_download(



    rid,



    fmt



):







    resultado = RESULTADOS.get(



        rid



    )







    if (



        not resultado



        or



        fmt not in (



            "csv",



            "xlsx"



        )



    ):







        return (



            "Resultado expirado. "



            "Execute a consulta novamente.",



            404



        )











    nome = (



        "consulta_"



        f"{time.strftime('%Y%m%d_%H%M%S')}"



        f".{fmt}"



    )











    # ========================================================



    # CSV



    # ========================================================







    if fmt == "csv":







        buffer_texto = (



            io.StringIO()



        )







        writer = csv.writer(



            buffer_texto,



            delimiter=";"



        )







        writer.writerow(



            resultado[



                "colunas"



            ]



        )







        writer.writerows(



            resultado[



                "linhas"



            ]



        )







        conteudo = (







            "\ufeff"







            +







            buffer_texto.getvalue()







        ).encode(



            "utf-8"



        )







        return send_file(







            io.BytesIO(



                conteudo



            ),







            mimetype=



                "text/csv",







            as_attachment=True,







            download_name=



                nome



        )











    # ========================================================



    # XLSX



    # ========================================================







    workbook = Workbook()







    worksheet = (



        workbook.active



    )







    worksheet.append(



        resultado[



            "colunas"



        ]



    )







    for linha in resultado[



        "linhas"



    ]:







        worksheet.append(



            list(



                linha



            )



        )







    output = (



        io.BytesIO()



    )







    workbook.save(



        output



    )







    output.seek(



        0



    )







    return send_file(







        output,







        as_attachment=True,







        download_name=



            nome,







        mimetype=(



            "application/"



            "vnd.openxmlformats-officedocument."



            "spreadsheetml.sheet"



        )



    )











# ============================================================



# INICIAR AUTOTASK



# ============================================================







if __name__ == "__main__":







    app.run(



        host="0.0.0.0",



        port=5000,



        debug=False



    )
