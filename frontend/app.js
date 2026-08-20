const $ = id => document.getElementById(id)
let token = null
let myCompany = null

function showError(msg){ alert(msg) }

async function post(path, body){
  const res = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json', ...(token?{Authorization:'Bearer '+token}:{})}, body: JSON.stringify(body)})
  return res.json()
}

$('login').onclick = async ()=>{
  const username = $('username').value
  const password = $('password').value
  if(!username || !password){ showError('사용자명과 비밀번호를 입력하세요'); return }
  const r = await post('/api/auth/login', {username,password})
  if(r.access_token){ token = r.access_token; $('auth').style.display='none'; $('app').style.display='block'; await loadMyCompany(); }
  else showError('로그인 실패')
}

async function loadMyCompany(){
  const res = await fetch('/api/my-company',{headers: token?{Authorization:'Bearer '+token}:{}})
  if(!res.ok){ showError('내 법인 정보를 불러오지 못했습니다'); return }
  const j = await res.json()
  myCompany = j
  $('mycompany').textContent = JSON.stringify(j)
  // set company field to user's company and lock unless admin
  $('company').value = j.company || ''
  if(j.company !== 'admin'){
    $('company').setAttribute('disabled','true')
  } else {
    $('company').removeAttribute('disabled')
  }
  // fetch companies list for optional UI later
  try{
    const c = await fetch('/api/companies',{headers: token?{Authorization:'Bearer '+token}:{}})
    if(c.ok){ const cl = await c.json(); console.log('companies', cl) }
  }catch(e){ /* ignore */ }
}

$('evaluate').onclick = async ()=>{
  // validation
  try{
    const related = JSON.parse($('related_sales').value || '{}')
    const company = $('company').value
    if(!company){ showError('법인을 선택하세요'); return }
    // ensure company matches logged-in user's company unless admin
    if(myCompany && myCompany.company !== 'admin' && company !== myCompany.company){ showError('자기 법인만 판정할 수 있습니다'); return }
    const operating_income = Number($('operating_income').value)
    const corporate_tax = Number($('corporate_tax').value)
    const total_sales = Number($('total_sales').value)
    if(Number.isNaN(operating_income) || Number.isNaN(corporate_tax) || Number.isNaN(total_sales)){
      showError('숫자 필드에 유효한 값을 입력하세요'); return
    }
    if(total_sales < 0 || operating_income < 0 || corporate_tax < 0){ showError('음수 값은 허용되지 않습니다'); return }

    const body = {
      company, operating_income, corporate_tax, total_sales, related_sales: related
    }
    const r = await post('/api/evaluate', body)
    if(r && r.reason) {
      $('result').textContent = JSON.stringify(r, null, 2)
    } else {
      showError('서버 응답을 확인하세요')
    }
  } catch(e){ showError('거래처 매출 JSON 형식이 올바르지 않습니다'); }
}
