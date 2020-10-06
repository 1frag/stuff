FROM python:3.8.6

WORKDIR /app

ADD . /app

RUN pip install -r requirements/singleton.txt
RUN python setup_singleton.py install
CMD ["python", "-m", "singleton"]
