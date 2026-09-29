-- Alta de UN administrador adicional.
-- Edita únicamente admin_email y admin_password antes de ejecutar.
-- Requiere que schema.sql (y migration_001_schedules.sql si aplica) ya estén ejecutados.

create extension if not exists pgcrypto;

do $$
declare
  new_admin_id uuid := gen_random_uuid();
  admin_email text := 'nuevo.admin@controlasist.com';
  admin_password text := 'CambiaEstaClave123';
begin
  if exists (select 1 from auth.users where email = admin_email) then
    raise exception 'Ya existe un usuario con el correo %', admin_email;
  end if;

  insert into auth.users (
    instance_id, id, aud, role, email, encrypted_password,
    email_confirmed_at, raw_app_meta_data, raw_user_meta_data,
    created_at, updated_at, confirmation_token, email_change,
    email_change_token_new, recovery_token
  )
  values (
    '00000000-0000-0000-0000-000000000000',
    new_admin_id,
    'authenticated',
    'authenticated',
    admin_email,
    crypt(admin_password, gen_salt('bf')),
    now(),
    '{"provider":"email","providers":["email"]}'::jsonb,
    '{}'::jsonb,
    now(),
    now(),
    '',
    '',
    '',
    ''
  );

  insert into auth.identities (
    provider_id, id, user_id, identity_data, provider, last_sign_in_at, created_at, updated_at
  )
  values (
    new_admin_id::text,
    new_admin_id,
    new_admin_id,
    jsonb_build_object('sub', new_admin_id::text, 'email', admin_email),
    'email',
    now(),
    now(),
    now()
  );

  insert into public.profiles (
    id, email, first_name, last_name, document_type,
    document_number_encrypted, role, employment_type
  )
  values (
    new_admin_id,
    admin_email,
    'Nuevo',
    'Admin',
    'Cédula de ciudadanía',
    'admin-created-by-seed',
    'admin',
    'employee'
  );
end $$;
