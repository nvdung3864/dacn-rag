import argparse,getpass
from sqlalchemy import select
from .db import Session,Base,engine
from .models import User
from .security import hash_password

def main():
    parser=argparse.ArgumentParser(description='Tạo tài khoản quản trị đầu tiên')
    parser.add_argument('--email',required=True);parser.add_argument('--name',default='Quản trị viên');args=parser.parse_args()
    password=getpass.getpass('Mật khẩu (tối thiểu 10 ký tự): ')
    if len(password)<10:raise SystemExit('Mật khẩu quá ngắn.')
    if engine.dialect.name=='sqlite':Base.metadata.create_all(engine)
    with Session() as db:
        if db.scalar(select(User).where(User.email==args.email.lower())):raise SystemExit('Email đã tồn tại.')
        db.add(User(email=args.email.lower(),name=args.name,password_hash=hash_password(password),role='admin'));db.commit()
    print('Đã tạo tài khoản quản trị.')
if __name__=='__main__':main()
