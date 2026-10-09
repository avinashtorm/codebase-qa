# Candidate review

Repo commit `7257e606cb94eada1dca40173e2b7f99dd549bc6`. 60 questions.

## c01 [where-is] Where is the JWT access token created?

[backend/app/core/security.py:22-26](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/backend/app/core/security.py#L22-L26)

```python
22  def create_access_token(subject: str | Any, expires_delta: timedelta) -> str:
23      expire = datetime.now(UTC) + expires_delta
24      to_encode = {"exp": expire, "sub": str(subject)}
25      encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)
26      return encoded_jwt
```

## c02 [where-is] Where are user passwords hashed?

[backend/app/core/security.py:35-36](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/backend/app/core/security.py#L35-L36)

```python
35  def get_password_hash(password: str) -> str:
36      return password_hash.hash(password)
```

## c03 [where-is] Where is the current user extracted from the bearer token in API requests?

[backend/app/api/deps.py:30-46](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/backend/app/api/deps.py#L30-L46)

```python
30  def get_current_user(session: SessionDep, token: TokenDep) -> User:
31      try:
32          payload = jwt.decode(
33              token, settings.SECRET_KEY, algorithms=[security.ALGORITHM]
34          )
35          token_data = TokenPayload(**payload)
36      except InvalidTokenError, ValidationError:
37          raise HTTPException(
38              status_code=status.HTTP_403_FORBIDDEN,
39              detail="Could not validate credentials",
40          )
41      user = session.get(User, token_data.sub)
42      if not user:
43          raise HTTPException(status_code=404, detail="User not found")
44      if not user.is_active:
45          raise HTTPException(status_code=400, detail="Inactive user")
46      return user
```

## c04 [where-is] Where is the login endpoint that returns an access token defined?

[backend/app/api/routes/login.py:23-42](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/backend/app/api/routes/login.py#L23-L42)

```python
23  @router.post("/login/access-token")
24  def login_access_token(
25      session: SessionDep, form_data: Annotated[OAuth2PasswordRequestForm, Depends()]
26  ) -> Token:
27      """
28      OAuth2 compatible token login, get an access token for future requests
29      """
30      user = crud.authenticate(
31          session=session, email=form_data.username, password=form_data.password
32      )
33      if not user:
34          raise HTTPException(status_code=400, detail="Incorrect email or password")
35      elif not user.is_active:
36          raise HTTPException(status_code=400, detail="Inactive user")
37      access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
38      return Token(
39          access_token=security.create_access_token(
40              user.id, expires_delta=access_token_expires
41          )
42      )
```

## c05 [where-is] Where is the check that the current user is a superuser implemented?

[backend/app/api/deps.py:52-57](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/backend/app/api/deps.py#L52-L57)

```python
52  def get_current_active_superuser(current_user: CurrentUser) -> User:
53      if not current_user.is_superuser:
54          raise HTTPException(
55              status_code=403, detail="The user doesn't have enough privileges"
56          )
57      return current_user
```

## c06 [where-is] Where are emails actually sent over SMTP?

[backend/app/utils.py:34-57](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/backend/app/utils.py#L34-L57)

```python
34  def send_email(
35      *,
36      email_to: str,
37      subject: str = "",
38      html_content: str = "",
39  ) -> None:
40      assert settings.emails_enabled, "no provided configuration for email variables"
41      assert settings.EMAILS_FROM_EMAIL  # For type checker
42      message = emails.message.Message(
43          subject=subject,
44          html=html_content,
45          mail_from=(settings.EMAILS_FROM_NAME, settings.EMAILS_FROM_EMAIL),
46      )
47      smtp_options = {"host": settings.SMTP_HOST, "port": settings.SMTP_PORT}
48      if settings.SMTP_TLS:
49          smtp_options["tls"] = True
50      elif settings.SMTP_SSL:
51          smtp_options["ssl"] = True
52      if settings.SMTP_USER:
53          smtp_options["user"] = settings.SMTP_USER
54      if settings.SMTP_PASSWORD:
55          smtp_options["password"] = settings.SMTP_PASSWORD
56      response = message.send(to=email_to, smtp=smtp_options)
57      logger.info(f"send email result: {response}")
```

## c07 [where-is] Where is the password reset token generated?

[backend/app/utils.py:105-115](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/backend/app/utils.py#L105-L115)

```python
105  def generate_password_reset_token(email: str) -> str:
106      delta = timedelta(hours=settings.EMAIL_RESET_TOKEN_EXPIRE_HOURS)
107      now = datetime.now(UTC)
108      expires = now + delta
109      exp = expires.timestamp()
110      encoded_jwt = jwt.encode(
111          {"exp": exp, "nbf": now, "sub": email},
112          settings.SECRET_KEY,
113          algorithm=security.ALGORITHM,
114      )
115      return encoded_jwt
```

## c08 [where-is] Where is the Item database table and its relationship to its owner defined?

[backend/app/models.py:87-93](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/backend/app/models.py#L87-L93)

```python
87  class Item(ItemBase, table=True):
88      id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
89      created_at: datetime | None = Field(default_factory=get_datetime_utc)
90      owner_id: uuid.UUID = Field(
91          foreign_key="user.id", nullable=False, ondelete="CASCADE"
92      )
93      owner: User | None = Relationship(back_populates="items")
```

## c09 [where-is] Where is CORS configured for the backend?

[backend/app/main.py:27-33](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/backend/app/main.py#L27-L33)

```python
27  app.add_middleware(
28      CORSMiddleware,
29      allow_origins=[settings.FRONTEND_HOST],
30      allow_credentials=True,
31      allow_methods=["*"],
32      allow_headers=["*"],
33  )
```

## c10 [where-is] Where are all the API route modules combined into one router?

[backend/app/api/main.py:6-14](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/backend/app/api/main.py#L6-L14)

```python
 6  api_router = APIRouter()
 7  api_router.include_router(login.router)
 8  api_router.include_router(users.router)
 9  api_router.include_router(utils.router)
10  api_router.include_router(items.router)
11  
12  
13  if settings.FASTAPI_ENV == "development":
14      api_router.include_router(private.router)
```

## c11 [where-is] Where is the first superuser created when the database is initialised?

[backend/app/core/db.py:15-33](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/backend/app/core/db.py#L15-L33)

```python
15  def init_db(session: Session) -> None:
16      # Tables should be created with Alembic migrations
17      # But if you don't want to use migrations, create
18      # the tables un-commenting the next lines
19      # from sqlmodel import SQLModel
20  
21      # This works because the models are already imported and registered from app.models
22      # SQLModel.metadata.create_all(engine)
23  
24      user = session.exec(
25          select(User).where(User.email == settings.FIRST_SUPERUSER)
26      ).first()
27      if not user:
28          user_in = UserCreate(
29              email=settings.FIRST_SUPERUSER,
30              password=settings.FIRST_SUPERUSER_PASSWORD,
31              is_superuser=True,
32          )
33          user = crud.create_user(session=session, user_create=user_in)
```

## c12 [where-is] Where does the frontend store the access token after a successful login?

[frontend/src/hooks/useAuth.ts:41-46](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/frontend/src/hooks/useAuth.ts#L41-L46)

```ts
41    const login = async (data: AccessToken) => {
42      const response = await LoginService.loginAccessToken({
43        body: data,
44      })
45      localStorage.setItem("access_token", response.data.access_token)
46    }
```

## c13 [where-is] Where are the sidebar navigation entries defined, including the admin link?

[frontend/src/components/Sidebar/AppSidebar.tsx:15-25](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/frontend/src/components/Sidebar/AppSidebar.tsx#L15-L25)

```tsx
15  const baseItems: Item[] = [
16    { icon: Home, title: "Dashboard", path: "/" },
17    { icon: Briefcase, title: "Items", path: "/items" },
18  ]
19  
20  export function AppSidebar() {
21    const { user: currentUser } = useAuth()
22  
23    const items = currentUser?.is_superuser
24      ? [...baseItems, { icon: Users, title: "Admin", path: "/admin" }]
25      : baseItems
```

## c14 [where-is] Where is the database session dependency for route handlers defined?

[backend/app/api/deps.py:21-26](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/backend/app/api/deps.py#L21-L26)

```python
21  def get_db() -> Generator[Session]:
22      with Session(engine) as session:
23          yield session
24  
25  
26  SessionDep = Annotated[Session, Depends(get_db)]
```

## c15 [where-is] Where is the health check endpoint implemented?

[backend/app/api/routes/utils.py:29-31](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/backend/app/api/routes/utils.py#L29-L31)

```python
29  @router.get("/health-check/")
30  async def health_check() -> bool:
31      return True
```

## c16 [where-is] Where are the HTML email templates rendered?

[backend/app/utils.py:25-31](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/backend/app/utils.py#L25-L31)

```python
25  def render_email_template(*, template_name: str, context: dict[str, Any]) -> str:
26      template_str = (
27          Path(__file__).parent / "email-templates" / template_name
28      ).read_text()
29      template: Template = Template(template_str)
30      html_content = template.render(context)
31      return html_content
```

## c17 [where-is] Where does the frontend configure the API base URL and attach the auth token to requests?

[frontend/src/main.tsx:17-20](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/frontend/src/main.tsx#L17-L20)

```tsx
17  client.setConfig({
18    baseURL: import.meta.env.VITE_API_URL ?? "",
19    auth: () => localStorage.getItem("access_token") || "",
20  })
```

## c18 [where-is] Where is the public user signup endpoint?

[backend/app/api/routes/users.py:146-159](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/backend/app/api/routes/users.py#L146-L159)

```python
146  @router.post("/signup", response_model=UserPublic)
147  def register_user(session: SessionDep, user_in: UserRegister) -> Any:
148      """
149      Create new user without the need to be logged in.
150      """
151      user = crud.get_user_by_email(session=session, email=user_in.email)
152      if user:
153          raise HTTPException(
154              status_code=400,
155              detail="The user with this email already exists in the system",
156          )
157      user_create = UserCreate.model_validate(user_in)
158      user = crud.create_user(session=session, user_create=user_create)
159      return user
```

## c19 [how-does] How does the backend authenticate a user's email and password?

[backend/app/crud.py:45-60](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/backend/app/crud.py#L45-L60)

```python
45  def authenticate(*, session: Session, email: str, password: str) -> User | None:
46      db_user = get_user_by_email(session=session, email=email)
47      if not db_user:
48          # Prevent timing attacks by running password verification even when user doesn't exist
49          # This ensures the response time is similar whether or not the email exists
50          verify_password(password, DUMMY_HASH)
51          return None
52      verified, updated_password_hash = verify_password(password, db_user.hashed_password)
53      if not verified:
54          return None
55      if updated_password_hash:
56          db_user.hashed_password = updated_password_hash
57          session.add(db_user)
58          session.commit()
59          session.refresh(db_user)
60      return db_user
```

## c20 [how-does] How does the backend validate a JWT and load the corresponding user?

[backend/app/api/deps.py:30-46](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/backend/app/api/deps.py#L30-L46)

```python
30  def get_current_user(session: SessionDep, token: TokenDep) -> User:
31      try:
32          payload = jwt.decode(
33              token, settings.SECRET_KEY, algorithms=[security.ALGORITHM]
34          )
35          token_data = TokenPayload(**payload)
36      except InvalidTokenError, ValidationError:
37          raise HTTPException(
38              status_code=status.HTTP_403_FORBIDDEN,
39              detail="Could not validate credentials",
40          )
41      user = session.get(User, token_data.sub)
42      if not user:
43          raise HTTPException(status_code=404, detail="User not found")
44      if not user.is_active:
45          raise HTTPException(status_code=400, detail="Inactive user")
46      return user
```

## c21 [how-does] How does login avoid leaking whether an email exists through response timing?

[backend/app/crud.py:40-51](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/backend/app/crud.py#L40-L51)

```python
40  # Dummy hash to use for timing attack prevention when user is not found
41  # This is an Argon2 hash of a random password, used to ensure constant-time comparison
42  DUMMY_HASH = "$argon2id$v=19$m=65536,t=3,p=4$MjQyZWE1MzBjYjJlZTI0Yw$YTU4NGM5ZTZmYjE2NzZlZjY0ZWY3ZGRkY2U2OWFjNjk"
43  
44  
45  def authenticate(*, session: Session, email: str, password: str) -> User | None:
46      db_user = get_user_by_email(session=session, email=email)
47      if not db_user:
48          # Prevent timing attacks by running password verification even when user doesn't exist
49          # This ensures the response time is similar whether or not the email exists
50          verify_password(password, DUMMY_HASH)
51          return None
```

## c22 [how-does] How are old password hashes upgraded when a user logs in?

[backend/app/crud.py:52-59](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/backend/app/crud.py#L52-L59)

```python
52      verified, updated_password_hash = verify_password(password, db_user.hashed_password)
53      if not verified:
54          return None
55      if updated_password_hash:
56          db_user.hashed_password = updated_password_hash
57          session.add(db_user)
58          session.commit()
59          session.refresh(db_user)
```

[backend/app/core/security.py:11-16](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/backend/app/core/security.py#L11-L16)

```python
11  password_hash = PasswordHash(
12      (
13          Argon2Hasher(),
14          BcryptHasher(),
15      )
16  )
```

[backend/app/core/security.py:29-32](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/backend/app/core/security.py#L29-L32)

```python
29  def verify_password(
30      plain_password: str, hashed_password: str
31  ) -> tuple[bool, str | None]:
32      return password_hash.verify_and_update(plain_password, hashed_password)
```

## c23 [how-does] How does password recovery avoid revealing whether an email address is registered?

[backend/app/api/routes/login.py:53-74](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/backend/app/api/routes/login.py#L53-L74)

```python
53  @router.post("/password-recovery/{email}")
54  def recover_password(email: str, session: SessionDep) -> Message:
55      """
56      Password Recovery
57      """
58      user = crud.get_user_by_email(session=session, email=email)
59  
60      # Always return the same response to prevent email enumeration attacks
61      # Only send email if user actually exists
62      if user:
63          password_reset_token = generate_password_reset_token(email=email)
64          email_data = generate_reset_password_email(
65              email_to=user.email, email=email, token=password_reset_token
66          )
67          send_email(
68              email_to=user.email,
69              subject=email_data.subject,
70              html_content=email_data.html_content,
71          )
72      return Message(
73          message="If that email is registered, we sent a password recovery link"
74      )
```

## c24 [how-does] How does listing items differ between superusers and normal users?

[backend/app/api/routes/items.py:13-45](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/backend/app/api/routes/items.py#L13-L45)

```python
13  @router.get("/", response_model=ItemsPublic)
14  def read_items(
15      session: SessionDep, current_user: CurrentUser, skip: int = 0, limit: int = 100
16  ) -> Any:
17      """
18      Retrieve items.
19      """
20  
21      if current_user.is_superuser:
22          count_statement = select(func.count()).select_from(Item)
23          count = session.exec(count_statement).one()
24          statement = (
25              select(Item).order_by(col(Item.created_at).desc()).offset(skip).limit(limit)
26          )
27          items = session.exec(statement).all()
28      else:
29          count_statement = (
30              select(func.count())
31              .select_from(Item)
32              .where(Item.owner_id == current_user.id)
33          )
34          count = session.exec(count_statement).one()
35          statement = (
36              select(Item)
37              .where(Item.owner_id == current_user.id)
38              .order_by(col(Item.created_at).desc())
39              .offset(skip)
40              .limit(limit)
41          )
42          items = session.exec(statement).all()
43  
44      items_public = [ItemPublic.model_validate(item) for item in items]
45      return ItemsPublic(data=items_public, count=count)
```

## c25 [how-does] How does the frontend prevent unauthenticated users from opening protected pages?

[frontend/src/routes/_layout.tsx:12-21](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/frontend/src/routes/_layout.tsx#L12-L21)

```tsx
12  export const Route = createFileRoute("/_layout")({
13    component: Layout,
14    beforeLoad: async () => {
15      if (!isLoggedIn()) {
16        throw redirect({
17          to: "/login",
18        })
19      }
20    },
21  })
```

[frontend/src/hooks/useAuth.ts:14-16](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/frontend/src/hooks/useAuth.ts#L14-L16)

```ts
14  const isLoggedIn = () => {
15    return localStorage.getItem("access_token") !== null
16  }
```

## c26 [how-does] How does the frontend react when the API responds with 401 or 403?

[frontend/src/main.tsx:22-38](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/frontend/src/main.tsx#L22-L38)

```tsx
22  const handleApiError = (error: Error) => {
23    if (
24      error instanceof AxiosError &&
25      [401, 403].includes(error.response?.status ?? 0)
26    ) {
27      localStorage.removeItem("access_token")
28      window.location.href = "/login"
29    }
30  }
31  const queryClient = new QueryClient({
32    queryCache: new QueryCache({
33      onError: handleApiError,
34    }),
35    mutationCache: new MutationCache({
36      onError: handleApiError,
37    }),
38  })
```

## c27 [how-does] How does a logged-in user change their own password on the backend?

[backend/app/api/routes/users.py:103-121](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/backend/app/api/routes/users.py#L103-L121)

```python
103  @router.patch("/me/password", response_model=Message)
104  def update_password_me(
105      *, session: SessionDep, body: UpdatePassword, current_user: CurrentUser
106  ) -> Any:
107      """
108      Update own password.
109      """
110      verified, _ = verify_password(body.current_password, current_user.hashed_password)
111      if not verified:
112          raise HTTPException(status_code=400, detail="Incorrect password")
113      if body.current_password == body.new_password:
114          raise HTTPException(
115              status_code=400, detail="New password cannot be the same as the current one"
116          )
117      hashed_password = get_password_hash(body.new_password)
118      current_user.hashed_password = hashed_password
119      session.add(current_user)
120      session.commit()
121      return Message(message="Password updated successfully")
```

## c28 [how-does] How are API errors turned into toast notifications in the frontend?

[frontend/src/utils.ts:3-20](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/frontend/src/utils.ts#L3-L20)

```ts
 3  function extractErrorMessage(err: Error): string {
 4    if (err instanceof AxiosError) {
 5      const errDetail = (err.response?.data as any)?.detail
 6      if (Array.isArray(errDetail) && errDetail.length > 0) {
 7        return errDetail[0].msg
 8      }
 9      if (typeof errDetail === "string") {
10        return errDetail
11      }
12      return err.message
13    }
14    return "Something went wrong."
15  }
16  
17  export const handleError = function (this: (msg: string) => void, err: Error) {
18    const errorMessage = extractErrorMessage(err)
19    this(errorMessage)
20  }
```

[frontend/src/hooks/useCustomToast.ts:10-14](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/frontend/src/hooks/useCustomToast.ts#L10-L14)

```ts
10    const showErrorToast = (description: string) => {
11      toast.error("Something went wrong!", {
12        description,
13      })
14    }
```

## c29 [how-does] How does the admin page make sure only superusers can open it?

[frontend/src/routes/_layout/admin.tsx:20-29](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/frontend/src/routes/_layout/admin.tsx#L20-L29)

```tsx
20  export const Route = createFileRoute("/_layout/admin")({
21    component: Admin,
22    beforeLoad: async () => {
23      const { data: user } = await UsersService.readUserMe()
24      if (!user.is_superuser) {
25        throw redirect({
26          to: "/",
27        })
28      }
29    },
```

## c30 [how-does] How is pagination implemented when listing users?

[backend/app/api/routes/users.py:32-51](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/backend/app/api/routes/users.py#L32-L51)

```python
32  @router.get(
33      "/",
34      dependencies=[Depends(get_current_active_superuser)],
35      response_model=UsersPublic,
36  )
37  def read_users(session: SessionDep, skip: int = 0, limit: int = 100) -> Any:
38      """
39      Retrieve users.
40      """
41  
42      count_statement = select(func.count()).select_from(User)
43      count = session.exec(count_statement).one()
44  
45      statement = (
46          select(User).order_by(col(User.created_at).desc()).offset(skip).limit(limit)
47      )
48      users = session.exec(statement).all()
49  
50      users_public = [UserPublic.model_validate(user) for user in users]
51      return UsersPublic(data=users_public, count=count)
```

## c31 [how-does] How does the reset password page get the token and submit the new password?

[frontend/src/routes/reset-password.tsx:28-30](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/frontend/src/routes/reset-password.tsx#L28-L30)

```tsx
28  const searchSchema = z.object({
29    token: z.string().catch(""),
30  })
```

[frontend/src/routes/reset-password.tsx:84-97](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/frontend/src/routes/reset-password.tsx#L84-L97)

```tsx
84    const mutation = useMutation({
85      mutationFn: (data: { new_password: string; token: string }) =>
86        LoginService.resetPassword({ body: data }),
87      onSuccess: () => {
88        showSuccessToast("Password updated successfully")
89        form.reset()
90        navigate({ to: "/login" })
91      },
92      onError: handleError.bind(showErrorToast),
93    })
94  
95    const onSubmit = (data: FormData) => {
96      mutation.mutate({ new_password: data.new_password, token })
97    }
```

## c32 [how-does] How is the selected colour theme remembered between visits?

[frontend/src/components/theme-provider.tsx:37-39](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/frontend/src/components/theme-provider.tsx#L37-L39)

```tsx
37    const [theme, setTheme] = useState<Theme>(
38      () => (localStorage.getItem(storageKey) as Theme) || defaultTheme,
39    )
```

[frontend/src/components/theme-provider.tsx:95-98](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/frontend/src/components/theme-provider.tsx#L95-L98)

```tsx
95      setTheme: (theme: Theme) => {
96        localStorage.setItem(storageKey, theme)
97        setTheme(theme)
98      },
```

## c33 [how-does] How do the end-to-end tests read the emails sent by the application?

[frontend/tests/utils/mailpit.ts:7-46](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/frontend/tests/utils/mailpit.ts#L7-L46)

```ts
 7  export async function waitForEmailHtml({
 8    request,
 9    query,
10    timeout = 5000,
11  }: {
12    request: APIRequestContext
13    query: string
14    timeout?: number
15  }) {
16    const deadline = Date.now() + timeout
17  
18    while (Date.now() < deadline) {
19      const response = await request.get(
20        `${process.env.MAILPIT_HOST}/api/v1/search`,
21        {
22          params: { query, limit: 1 },
23        },
24      )
25      const { messages }: { messages: EmailSummary[] } = await response.json()
26      const email = messages[0]
27  
28      if (email) {
29        const htmlResponse = await request.get(
30          `${process.env.MAILPIT_HOST}/view/${email.ID}.html`,
31        )
32  
33        if (!htmlResponse.ok()) {
34          throw new Error(
35            `Could not get the HTML for email "${email.ID}": ${htmlResponse.status()}`,
36          )
37        }
38  
39        return htmlResponse.text()
40      }
41  
42      await new Promise((resolve) => setTimeout(resolve, 100))
43    }
44  
45    throw new Error(`Timeout while trying to get the latest email for "${query}"`)
46  }
```

## c34 [how-does] How does the backend serve the built frontend files?

[backend/app/main.py:11-11](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/backend/app/main.py#L11-L11)

```python
11  FRONTEND_DIR = Path(__file__).parent / "frontend"
```

[backend/app/main.py:36-36](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/backend/app/main.py#L36-L36)

```python
36  app.frontend("/", directory=FRONTEND_DIR)
```

[frontend/vite.config.ts:9-12](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/frontend/vite.config.ts#L9-L12)

```ts
 9    build: {
10      outDir: "../backend/app/frontend",
11      emptyOutDir: true,
12    },
```

## c35 [what-happens-when] What happens when a user tries to log in with a wrong password?

[backend/app/api/routes/login.py:30-34](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/backend/app/api/routes/login.py#L30-L34)

```python
30      user = crud.authenticate(
31          session=session, email=form_data.username, password=form_data.password
32      )
33      if not user:
34          raise HTTPException(status_code=400, detail="Incorrect email or password")
```

[backend/app/crud.py:52-54](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/backend/app/crud.py#L52-L54)

```python
52      verified, updated_password_hash = verify_password(password, db_user.hashed_password)
53      if not verified:
54          return None
```

## c36 [what-happens-when] What happens when an inactive user tries to log in?

[backend/app/api/routes/login.py:35-36](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/backend/app/api/routes/login.py#L35-L36)

```python
35      elif not user.is_active:
36          raise HTTPException(status_code=400, detail="Inactive user")
```

## c37 [what-happens-when] What happens when a superuser tries to delete their own account?

[backend/app/api/routes/users.py:132-143](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/backend/app/api/routes/users.py#L132-L143)

```python
132  @router.delete("/me", response_model=Message)
133  def delete_user_me(session: SessionDep, current_user: CurrentUser) -> Any:
134      """
135      Delete own user.
136      """
137      if current_user.is_superuser:
138          raise HTTPException(
139              status_code=403, detail="Super users are not allowed to delete themselves"
140          )
141      session.delete(current_user)
142      session.commit()
143      return Message(message="User deleted successfully")
```

## c38 [what-happens-when] What happens to a user's items when an admin deletes that user?

[backend/app/api/routes/users.py:214-232](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/backend/app/api/routes/users.py#L214-L232)

```python
214  @router.delete("/{user_id}", dependencies=[Depends(get_current_active_superuser)])
215  def delete_user(
216      session: SessionDep, current_user: CurrentUser, user_id: uuid.UUID
217  ) -> Message:
218      """
219      Delete a user.
220      """
221      user = session.get(User, user_id)
222      if not user:
223          raise HTTPException(status_code=404, detail="User not found")
224      if user == current_user:
225          raise HTTPException(
226              status_code=403, detail="Super users are not allowed to delete themselves"
227          )
228      statement = delete(Item).where(col(Item.owner_id) == user_id)
229      session.exec(statement)
230      session.delete(user)
231      session.commit()
232      return Message(message="User deleted successfully")
```

[backend/app/models.py:90-92](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/backend/app/models.py#L90-L92)

```python
90      owner_id: uuid.UUID = Field(
91          foreign_key="user.id", nullable=False, ondelete="CASCADE"
92      )
```

## c39 [what-happens-when] What happens when a normal user requests an item that belongs to someone else?

[backend/app/api/routes/items.py:48-58](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/backend/app/api/routes/items.py#L48-L58)

```python
48  @router.get("/{id}", response_model=ItemPublic)
49  def read_item(session: SessionDep, current_user: CurrentUser, id: uuid.UUID) -> Any:
50      """
51      Get item by ID.
52      """
53      item = session.get(Item, id)
54      if not item:
55          raise HTTPException(status_code=404, detail="Item not found")
56      if not current_user.is_superuser and (item.owner_id != current_user.id):
57          raise HTTPException(status_code=403, detail="Not enough permissions")
58      return item
```

## c40 [what-happens-when] What happens when someone signs up with an email that is already registered?

[backend/app/api/routes/users.py:146-159](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/backend/app/api/routes/users.py#L146-L159)

```python
146  @router.post("/signup", response_model=UserPublic)
147  def register_user(session: SessionDep, user_in: UserRegister) -> Any:
148      """
149      Create new user without the need to be logged in.
150      """
151      user = crud.get_user_by_email(session=session, email=user_in.email)
152      if user:
153          raise HTTPException(
154              status_code=400,
155              detail="The user with this email already exists in the system",
156          )
157      user_create = UserCreate.model_validate(user_in)
158      user = crud.create_user(session=session, user_create=user_create)
159      return user
```

## c41 [what-happens-when] What happens when a password reset token is invalid or expired?

[backend/app/api/routes/login.py:77-90](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/backend/app/api/routes/login.py#L77-L90)

```python
77  @router.post("/reset-password/")
78  def reset_password(session: SessionDep, body: NewPassword) -> Message:
79      """
80      Reset password
81      """
82      email = verify_password_reset_token(token=body.token)
83      if not email:
84          raise HTTPException(status_code=400, detail="Invalid token")
85      user = crud.get_user_by_email(session=session, email=email)
86      if not user:
87          # Don't reveal that the user doesn't exist - use same error as invalid token
88          raise HTTPException(status_code=400, detail="Invalid token")
89      elif not user.is_active:
90          raise HTTPException(status_code=400, detail="Inactive user")
```

[backend/app/utils.py:118-125](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/backend/app/utils.py#L118-L125)

```python
118  def verify_password_reset_token(token: str) -> str | None:
119      try:
120          decoded_token = jwt.decode(
121              token, settings.SECRET_KEY, algorithms=[security.ALGORITHM]
122          )
123          return str(decoded_token["sub"])
124      except InvalidTokenError:
125          return None
```

## c42 [what-happens-when] What happens when an admin creates a new user while emails are enabled?

[backend/app/api/routes/users.py:57-78](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/backend/app/api/routes/users.py#L57-L78)

```python
57  def create_user(*, session: SessionDep, user_in: UserCreate) -> Any:
58      """
59      Create new user.
60      """
61      user = crud.get_user_by_email(session=session, email=user_in.email)
62      if user:
63          raise HTTPException(
64              status_code=400,
65              detail="The user with this email already exists in the system.",
66          )
67  
68      user = crud.create_user(session=session, user_create=user_in)
69      if settings.emails_enabled and user_in.email:
70          email_data = generate_new_account_email(
71              email_to=user_in.email, username=user_in.email, password=user_in.password
72          )
73          send_email(
74              email_to=user_in.email,
75              subject=email_data.subject,
76              html_content=email_data.html_content,
77          )
78      return user
```

## c43 [what-happens-when] What happens when the JWT sent with a request cannot be decoded?

[backend/app/api/deps.py:31-40](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/backend/app/api/deps.py#L31-L40)

```python
31      try:
32          payload = jwt.decode(
33              token, settings.SECRET_KEY, algorithms=[security.ALGORITHM]
34          )
35          token_data = TokenPayload(**payload)
36      except InvalidTokenError, ValidationError:
37          raise HTTPException(
38              status_code=status.HTTP_403_FORBIDDEN,
39              detail="Could not validate credentials",
40          )
```

## c44 [what-happens-when] What happens when a user tries to change their password to the current password?

[backend/app/api/routes/users.py:110-116](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/backend/app/api/routes/users.py#L110-L116)

```python
110      verified, _ = verify_password(body.current_password, current_user.hashed_password)
111      if not verified:
112          raise HTTPException(status_code=400, detail="Incorrect password")
113      if body.current_password == body.new_password:
114          raise HTTPException(
115              status_code=400, detail="New password cannot be the same as the current one"
116          )
```

## c45 [what-happens-when] What happens when a user changes their email to one already used by another account?

[backend/app/api/routes/users.py:89-94](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/backend/app/api/routes/users.py#L89-L94)

```python
89      if user_in.email:
90          existing_user = crud.get_user_by_email(session=session, email=user_in.email)
91          if existing_user and existing_user.id != current_user.id:
92              raise HTTPException(
93                  status_code=409, detail="User with this email already exists"
94              )
```

## c46 [what-happens-when] What happens if SECRET_KEY is left as changethis outside development?

[backend/app/core/config.py:68-88](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/backend/app/core/config.py#L68-L88)

```python
68      def _check_default_secret(self, var_name: str, value: str | None) -> None:
69          if value == "changethis":
70              message = (
71                  f'The value of {var_name} is "changethis", '
72                  "for security, please change it, at least for deployments."
73              )
74              if self.FASTAPI_ENV == "development":
75                  warnings.warn(message, stacklevel=1)
76              else:
77                  raise ValueError(message)
78  
79      @model_validator(mode="after")
80      def _enforce_non_default_secrets(self) -> Self:
81          self._check_default_secret("SECRET_KEY", self.SECRET_KEY)
82          for host in self.DATABASE_URL.hosts():
83              self._check_default_secret("DATABASE_URL password", host["password"])
84          self._check_default_secret(
85              "FIRST_SUPERUSER_PASSWORD", self.FIRST_SUPERUSER_PASSWORD
86          )
87  
88          return self
```

## c47 [what-happens-when] What happens in the frontend after a successful login?

[frontend/src/hooks/useAuth.ts:41-54](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/frontend/src/hooks/useAuth.ts#L41-L54)

```ts
41    const login = async (data: AccessToken) => {
42      const response = await LoginService.loginAccessToken({
43        body: data,
44      })
45      localStorage.setItem("access_token", response.data.access_token)
46    }
47  
48    const loginMutation = useMutation({
49      mutationFn: login,
50      onSuccess: () => {
51        navigate({ to: "/" })
52      },
53      onError: handleError.bind(showErrorToast),
54    })
```

## c48 [what-happens-when] What happens in the UI after a password change succeeds in user settings?

[frontend/src/components/UserSettings/ChangePassword.tsx:54-62](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/frontend/src/components/UserSettings/ChangePassword.tsx#L54-L62)

```tsx
54    const mutation = useMutation({
55      mutationFn: (data: UpdatePassword) =>
56        UsersService.updatePasswordMe({ body: data }),
57      onSuccess: () => {
58        showSuccessToast("Password updated successfully")
59        form.reset()
60      },
61      onError: handleError.bind(showErrorToast),
62    })
```

## c49 [what-happens-when] What happens when an admin deletes a user from the admin UI?

[frontend/src/components/Admin/DeleteUser.tsx:33-48](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/frontend/src/components/Admin/DeleteUser.tsx#L33-L48)

```tsx
33    const deleteUser = async (id: string) => {
34      await UsersService.deleteUser({ path: { user_id: id } })
35    }
36  
37    const mutation = useMutation({
38      mutationFn: deleteUser,
39      onSuccess: () => {
40        showSuccessToast("The user was deleted successfully")
41        setIsOpen(false)
42        onSuccess()
43      },
44      onError: handleError.bind(showErrorToast),
45      onSettled: () => {
46        queryClient.invalidateQueries()
47      },
48    })
```

## c50 [what-happens-when] What happens at startup when a Sentry DSN is configured?

[backend/app/main.py:18-19](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/backend/app/main.py#L18-L19)

```python
18  if settings.SENTRY_DSN and settings.FASTAPI_ENV != "development":
19      sentry_sdk.init(dsn=str(settings.SENTRY_DSN), enable_tracing=True)
```

## c51 [config] How long is an access token valid by default?

[backend/app/core/config.py:24-25](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/backend/app/core/config.py#L24-L25)

```python
24      # 60 minutes * 24 hours * 8 days = 8 days
25      ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 8
```

## c52 [config] How is the DATABASE_URL adjusted to use the psycopg driver?

[backend/app/core/config.py:33-40](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/backend/app/core/config.py#L33-L40)

```python
33      @field_validator("DATABASE_URL", mode="before")
34      @classmethod
35      def _use_psycopg_driver(cls, value: str | PostgresDsn) -> str:
36          database_url = str(value)
37          for scheme in ("postgres://", "postgresql://"):
38              if database_url.startswith(scheme):
39                  return database_url.replace(scheme, "postgresql+psycopg://", 1)
40          return database_url
```

## c53 [config] Which settings decide whether sending emails is enabled?

[backend/app/core/config.py:59-62](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/backend/app/core/config.py#L59-L62)

```python
59      @computed_field  # type: ignore[prop-decorator]
60      @property
61      def emails_enabled(self) -> bool:
62          return bool(self.SMTP_HOST and self.EMAILS_FROM_EMAIL)
```

## c54 [config] Which ports does the local Mailpit mail catcher expose in development?

[compose.override.yml:66-75](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/compose.override.yml#L66-L75)

```yaml
66        FASTAPI_ENV: "development"
67        SMTP_HOST: "mailpit"
68        SMTP_PORT: "1025"
69        SMTP_TLS: "false"
70  
71    mailpit:
72      image: axllent/mailpit
73      ports:
74        - "8025:8025"
75        - "1025:1025"
```

## c55 [config] How long is a password reset token valid?

[backend/app/core/config.py:57-57](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/backend/app/core/config.py#L57-L57)

```python
57      EMAIL_RESET_TOKEN_EXPIRE_HOURS: int = 48
```

[backend/app/utils.py:106-106](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/backend/app/utils.py#L106-L106)

```python
106      delta = timedelta(hours=settings.EMAIL_RESET_TOKEN_EXPIRE_HOURS)
```

## c56 [config] Which environment variables does the backend container need in docker compose?

[compose.yml:55-65](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/compose.yml#L55-L65)

```yaml
55      environment:
56        PROJECT_NAME: ${PROJECT_NAME:?Variable not set}
57        SECRET_KEY: ${SECRET_KEY:?Variable not set}
58        FIRST_SUPERUSER: ${FIRST_SUPERUSER:?Variable not set}
59        FIRST_SUPERUSER_PASSWORD: ${FIRST_SUPERUSER_PASSWORD:?Variable not set}
60        SMTP_HOST: ${SMTP_HOST}
61        SMTP_USER: ${SMTP_USER:-}
62        SMTP_PASSWORD: ${SMTP_PASSWORD:-}
63        EMAILS_FROM_EMAIL: ${EMAILS_FROM_EMAIL}
64        DATABASE_URL: postgresql://postgres:${POSTGRES_PASSWORD:?Variable not set}@db:5432/app
65        SENTRY_DSN: ${SENTRY_DSN:-}
```

## c57 [config] How are database migrations and initial data applied before the backend starts?

[backend/scripts/prestart.sh:6-10](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/backend/scripts/prestart.sh#L6-L10)

```bash
 6  # Run migrations
 7  alembic upgrade head
 8  
 9  # Create initial data in DB
10  python app/initial_data.py
```

## c58 [config] How is the backend container health check configured in docker compose?

[compose.yml:67-71](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/compose.yml#L67-L71)

```yaml
67      healthcheck:
68        test: ["CMD", "curl", "-f", "http://localhost:8000/api/v1/utils/health-check/"]
69        interval: 10s
70        timeout: 5s
71        retries: 5
```

## c59 [config] What are the default superuser credentials in the development environment file?

[.env:6-8](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/.env#L6-L8)

```
6  SECRET_KEY=changethis
7  FIRST_SUPERUSER=admin@example.com
8  FIRST_SUPERUSER_PASSWORD=changethis
```

## c60 [config] When are the private API routes enabled?

[backend/app/api/main.py:13-14](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/backend/app/api/main.py#L13-L14)

```python
13  if settings.FASTAPI_ENV == "development":
14      api_router.include_router(private.router)
```

[backend/app/core/config.py:27-27](https://github.com/fastapi/full-stack-fastapi-template/blob/7257e606cb94eada1dca40173e2b7f99dd549bc6/backend/app/core/config.py#L27-L27)

```python
27      FASTAPI_ENV: Literal["development"] | None = None
```
