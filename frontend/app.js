const $ = id => document.getElementById(id)
let token = null
let myCompany = null
let lastReviewInput = null
// 거래처 표와 엑셀 업로드 결과가 같은 목록을 써야 한다. /api/companies 응답을 그대로 담는다.
let allCompanies = []
// 서버 calc.OTHER_COMPANY 와 같은 문자열이어야 한다. /api/companies 목록에 포함돼 내려온다.
const OTHER_COMPANY = '기타법인'

function showError(msg){
  const formError = $('form-error')
  if(formError && $('result-page').style.display === 'none'){
    formError.textContent = msg
    return
  }
  const el = $('result')
  el.innerHTML = `<div style="color:#b91c1c;font-weight:700">오류</div><div style="margin-top:6px">${escapeHtml(msg)}</div>`
  el.style.borderColor = '#f8d7da'
}

async function post(path, body){
  const res = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json', ...(token?{Authorization:'Bearer '+token}:{})}, body: JSON.stringify(body)})
  const data = await res.json().catch(()=>null)
  if(!res.ok){
    const detail = data && (data.detail || data.message)
    throw new Error(detail || `서버 오류 (${res.status})`)
  }
  return data
}

function showLoginError(msg){
  const el = $('login-error')
  if(el) el.textContent = msg
}

// 로그인은 서버 인증만 사용한다. 이 화면 자체를 백엔드가 서빙하므로(StaticFiles 마운트)
// 페이지가 열렸다면 API 는 이미 떠 있다 — 개발용 mock 로그인은 반쪽짜리 세션만 만들어 제거했다.
$('login').onclick = async ()=>{
  const username = $('username').value
  const password = $('password').value
  showLoginError('')
  if(!username || !password){ showLoginError('사용자명과 비밀번호를 입력하세요'); return }
  try{
    const j = await post('/api/auth/login', {username, password})
    if(!j || !j.access_token) throw new Error('서버 응답에 토큰이 없습니다')
    token = j.access_token
    $('login-overlay').style.display = 'none'
    $('app').style.display = 'block'
    await loadMyCompany()
  }catch(e){
    token = null
    showLoginError(e.message || '로그인에 실패했습니다')
  }
}

// 로그인 카드는 <form> 이 아니라 Enter 가 먹지 않는다. 두 입력란 모두에서 Enter 로 제출되게 한다.
;['username','password'].forEach(id=>{
  $(id)?.addEventListener('keydown', e=>{ if(e.key === 'Enter'){ e.preventDefault(); $('login').click() } })
})

// Table helpers for related sales and tax adjustments
// 0 인 행은 계산에 영향이 없고(서버가 0 매출을 건너뛴다) 결과 리포트만 지저분하게 만들어 제외한다.
function getRelatedFromTable(){
  const tbody = document.querySelector('#related_table tbody')
  if(!tbody) return {}
  const related = {}
  Array.from(tbody.querySelectorAll('tr')).forEach(tr=>{
    const name = tr.dataset.company || ''
    const amtEl = tr.querySelector('.ramt')
    const amt = Number(amtEl && amtEl.value ? amtEl.value : 0)
    if(name && amt) related[name] = amt
  })
  return related
}

// 지배주주별 배당소득. 관리자에게만 표가 그려지므로 그 외에는 빈 객체가 된다.
function getDividendFromTable(){
  const tbody = document.querySelector('#dividend_table tbody')
  if(!tbody) return {}
  const out = {}
  Array.from(tbody.querySelectorAll('tr')).forEach(tr=>{
    const code = tr.dataset.code || ''
    const v = Number(tr.querySelector('.dvd')?.value || 0)
    if(code && v) out[code] = v
  })
  return out
}

// 관리자에게만 배당소득 공제 입력란을 그린다.
function renderDividendSection(codes){
  const section = document.getElementById('dividend-section')
  const tbody = document.querySelector('#dividend_table tbody')
  if(!section || !tbody) return
  if(!codes || !codes.length){ section.style.display = 'none'; return }
  section.style.display = ''
  tbody.innerHTML = codes.map(code => `
    <tr data-code="${escapeHtml(code)}"><td>${escapeHtml(code)}</td><td><input class="dvd" type="number" min="0" value="0" placeholder="0"></td></tr>
  `).join('')
}

// 제10항 과세제외액. 매출이 0 인 행은 서버가 건너뛰므로 함께 뺀다.
function getArticle10FromTable(){
  const tbody = document.querySelector('#related_table tbody')
  if(!tbody) return {}
  const out = {}
  Array.from(tbody.querySelectorAll('tr')).forEach(tr=>{
    const name = tr.dataset.company || ''
    const amt = Number(tr.querySelector('.ramt')?.value || 0)
    const ex = Number(tr.querySelector('.rex')?.value || 0)
    if(name && amt && ex) out[name] = ex
  })
  return out
}

function getTaxFromTable(){
  const tbody = document.querySelector('#tax_table tbody')
  if(!tbody) return {}
  const obj = {}
  Array.from(tbody.querySelectorAll('tr')).forEach(tr=>{
    const name = tr.dataset.taxItem || ''
    const amtEl = tr.querySelector('.tamt')
    const amt = Number(amtEl && amtEl.value ? amtEl.value : 0)
    if(name && amt) obj[name] = amt
  })
  return obj
}

document.addEventListener('input', (e)=>{
  if(e.target && e.target.classList.contains('tamt')) updateTaxTotal()
})

function updateTaxTotal(){
  const total = Array.from(document.querySelectorAll('#tax_table .tamt'))
    .reduce((sum, input) => sum + (Number(input.value) || 0), 0)
  if($('tax-total')) $('tax-total').value = `${formatNum(total)}원`
}

// Download handlers: simple CSV export and print
document.getElementById('excel-download')?.addEventListener('click', ()=>{
  // build CSV from related and tax tables
  const related = getRelatedFromTable()
  const tax = getTaxFromTable()
  const cell = s => `"${String(s).replace(/"/g,'""')}"`
  let csv = '구분,항목,금액\n'
  Object.entries(related).forEach(([k,v])=> csv += `특수관계자매출,${cell(k)},${v}\n`)
  Object.entries(tax).forEach(([k,v])=> csv += `세무조정,${cell(k)},${v}\n`)
  // Excel 은 BOM 이 없는 UTF-8 CSV 를 ANSI 로 열어 한글이 깨진다.
  const BOM = String.fromCharCode(0xFEFF)
  const blob = new Blob([BOM + csv], {type:'text/csv;charset=utf-8;'});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a'); a.href = url; a.download = 'report_export.csv'; document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
})

document.getElementById('pdf-download')?.addEventListener('click', ()=>{
  window.print()
})

// --- 검토 연도 ---------------------------------------------------------------
// 지분·기업규모·세율은 해마다 바뀌므로 서버가 연도별 데이터를 들고 있다.
// 화면은 연도를 골라 보내기만 하고, 어떤 데이터가 쓰였는지는 응답의 year 로 확인한다.

let currentYear = null
let yearAsOf = {}    // {연도: 기준시점 문구}

function yearQuery(prefix = '?'){
  return currentYear ? `${prefix}year=${encodeURIComponent(currentYear)}` : ''
}

function updateYearHint(){
  const el = $('year-as-of')
  if(!el) return
  const asOf = yearAsOf[currentYear]
  el.textContent = asOf
    ? `기준시점: ${asOf}`
    : '서버에 저장된 연도별 지분·규모 데이터로 계산합니다.'
}

async function apiGet(path){
  const res = await fetch(path, {headers: token ? {Authorization:'Bearer '+token} : {}})
  const data = await res.json().catch(()=>null)
  if(!res.ok) throw new Error((data && data.detail) || `서버 오류 (${res.status})`)
  return data
}

async function loadYears(){
  const select = $('data_year')
  if(!select) return
  try{
    const j = await apiGet('/api/years')
    const years = j.years || []
    yearAsOf = {}
    years.forEach(o => { yearAsOf[o.year] = o.as_of || '' })
    select.innerHTML = years
      .map(o => `<option value="${escapeHtml(o.year)}">${escapeHtml(o.year)}년</option>`).join('')
    currentYear = j.default || (years[0] && years[0].year) || null
    if(currentYear) select.value = currentYear
    // 연도가 하나뿐이면 고를 것이 없다.
    select.disabled = years.length <= 1
  }catch(e){
    select.innerHTML = '<option value="">(연도를 불러오지 못했습니다)</option>'
    select.disabled = true
  }
  updateYearHint()
}

async function loadMyCompany(){
  await loadYears()
  await refreshForYear({preserveAmounts: false})
}

async function refreshForYear({preserveAmounts = true} = {}){
  // 연도를 바꿔도 이미 입력한 금액을 날리지 않는다. 그 연도에 없는 거래처만 빠진다.
  const previous = preserveAmounts ? getRelatedFromTable() : null

  let j
  try{
    j = await apiGet(`/api/my-company${yearQuery()}`)
  }catch(e){
    showError(e.message || '내 법인 정보를 불러오지 못했습니다')
    return
  }
  myCompany = j
  renderDividendSection(j && j.shareholder_codes)
  $('mycompany').textContent = j.size ? `${j.company} · ${j.size}` : (j.company || '')
  $('hint').textContent = ''

  const companySelect = $('company')
  const keepCompany = companySelect.value
  // Populate only the public company-name list. Sensitive ownership data stays server-side.
  try{
    const cl = await apiGet(`/api/companies${yearQuery()}`)
    const all = cl.companies || []
    allCompanies = all
    companySelect.innerHTML = '<option value="">법인을 선택하세요</option>'
    // 판정 대상은 실제 법인만 — 기타법인은 거래처(매출 입력)로만 쓰인다.
    all.filter(name => name !== OTHER_COMPANY).forEach(name=>{
      const option = document.createElement('option')
      option.value = name
      option.textContent = name
      companySelect.appendChild(option)
    })
    // 거래처 표는 서버 목록을 그대로 쓴다. 프론트에서 이름을 만들지 않는다.
    renderRelatedCompanies(all)
    if(keepCompany && all.includes(keepCompany)) companySelect.value = keepCompany
  }catch(e){
    showError(e.message || '법인 목록을 불러오지 못했습니다')
    return
  }

  if(previous){
    applyRelatedAmounts(previous)
    // 사라진 거래처에 금액이 있었다면 조용히 넘어가지 않고 알린다.
    const dropped = Object.keys(previous)
      .filter(name => Number(previous[name]) > 0 && !allCompanies.includes(name))
    setImportStatus(dropped.length
      ? `${currentYear}년 데이터에 없는 거래처 ${dropped.length}건의 입력값이 빠졌습니다: ${dropped.join(', ')}`
      : '')
  }

  if(j.company !== 'admin'){
    companySelect.value = j.company || ''
    companySelect.setAttribute('disabled','true')
    $('hint').textContent = '(관리자 아님 — 법인 필드 잠김)'
    // 기업 구분은 서버가 보유한 값이 유일한 근거다. 관리자는 법인을 바꿀 수 있어
    // 판정 전까지 알 수 없으므로, 최종 표시는 응답의 size(renderReport)를 따른다.
    if(j.size && ['일반','중견','중소'].includes(j.size)) $('company_size').value = j.size
  } else {
    $('rawdata-button').style.display = 'inline-block'
    companySelect.removeAttribute('disabled')
    if(companySelect.options.length > 1 && !companySelect.value) companySelect.value = companySelect.options[1].value
    // 관리자는 법인을 바꿀 수 있어 판정 전에는 기업 구분을 알 수 없다.
    $('company_size').value = ''
  }
}

document.getElementById('data_year')?.addEventListener('change', async (e)=>{
  currentYear = e.target.value || null
  updateYearHint()
  // 연도가 바뀌면 지분·규모·법인 목록이 통째로 달라진다. 엑셀 반영 결과도 무효다.
  const box = $('import-report')
  if(box){ box.style.display = 'none'; box.innerHTML = '' }
  relatedSnapshot = null
  lastImport = null
  await refreshForYear({preserveAmounts: true})
})

function renderRelatedCompanies(companies){
  const tbody = document.querySelector('#related_table tbody')
  if(!tbody) return
  tbody.innerHTML = companies.map(name => `
    <tr data-company="${escapeHtml(name)}"><td>${escapeHtml(name)}</td><td><input class="ramt" type="number" min="0" value="0" placeholder="0"></td><td><input class="rex" type="number" min="0" value="0" placeholder="0"></td></tr>
  `).join('')
}

// --- 엑셀 업로드 -------------------------------------------------------------
// 서버가 파일을 읽어 거래처별 금액만 돌려준다. 표를 채우는 것은 여기서 한다.
// 서버는 아무것도 저장하지 않으므로, 사용자가 표를 확인하고 '확인'을 눌러야 계산된다.

let relatedSnapshot = null   // 업로드 직전 표 상태 — 되돌리기용
let lastImport = null        // 미매칭 거래처를 나중에 반영하기 위해 들고 있는다

function snapshotRelated(){
  const snap = {}
  document.querySelectorAll('#related_table tbody tr').forEach(tr=>{
    const input = tr.querySelector('.ramt')
    const ex = tr.querySelector('.rex')
    snap[tr.dataset.company || ''] = {amount: input ? input.value : '0', article10: ex ? ex.value : '0'}
  })
  return snap
}

// 값은 숫자(매출액만) 또는 {amount, article10} 둘 다 받는다. 스냅샷 되돌리기가 후자를 쓴다.
function applyRelatedAmounts(amounts, {reset = false} = {}){
  document.querySelectorAll('#related_table tbody tr').forEach(tr=>{
    const name = tr.dataset.company || ''
    const input = tr.querySelector('.ramt')
    const ex = tr.querySelector('.rex')
    if(!input) return
    if(reset){ input.value = 0; if(ex) ex.value = 0 }
    if(!Object.prototype.hasOwnProperty.call(amounts, name)) return
    const v = amounts[name]
    if(v !== null && typeof v === 'object'){
      input.value = v.amount ?? 0
      if(ex) ex.value = v.article10 ?? 0
    } else {
      input.value = v
    }
  })
}

// 법인명을 선택자에 끼워 넣지 않고 행을 훑어 비교한다. 이름에 따옴표·공백이 있어도 안전하고,
// 표를 그릴 때 쓴 dataset 값과 정확히 같은 문자열로 맞춰볼 수 있다.
function addRelatedAmount(company, amount, article10){
  const rows = Array.from(document.querySelectorAll('#related_table tbody tr'))
  const tr = rows.find(row => (row.dataset.company || '') === company)
  const input = tr && tr.querySelector('.ramt')
  if(!input) return false
  input.value = (Number(input.value) || 0) + amount
  const ex = tr.querySelector('.rex')
  if(ex && article10) ex.value = (Number(ex.value) || 0) + article10
  return true
}

function setImportStatus(msg){
  const el = $('import-status')
  if(el) el.textContent = msg
}

function showImportError(msg){
  const box = $('import-report')
  if(!box) return
  box.className = 'import-report error'
  box.style.display = 'block'
  box.innerHTML = `<div class="import-fail">엑셀을 읽지 못했습니다</div><div style="margin-top:6px">${escapeHtml(msg)}</div>`
}

function renderImportReport(result){
  const box = $('import-report')
  if(!box) return
  const stats = result.stats || {}
  const warnings = (result.warnings || [])
    .map(w => `<div class="import-warn">${escapeHtml(w)}</div>`).join('')

  // 미매칭은 버리지 않는다. 어느 법인으로 넣을지 사용자가 직접 고른다.
  const unmatched = result.unmatched || []
  const options = allCompanies
    .map(c => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join('')
  const unmatchedBlock = unmatched.length ? `
    <div style="margin-top:12px">
      <strong style="font-size:13px">목록에 없는 거래처 ${unmatched.length}건</strong>
      <div class="hint" style="margin-top:4px">그대로 두면 계산에 들어가지 않습니다. 넣을 법인을 고른 뒤 아래 버튼을 누르세요.</div>
      <table class="unmatched-table">
        <thead><tr><th>파일의 거래처명</th><th style="text-align:right">매출액</th><th style="width:190px">연결할 법인</th></tr></thead>
        <tbody>
          ${unmatched.map((u, i) => `
            <tr data-unmatched-index="${i}">
              <td>${escapeHtml(u.name)}</td>
              <td class="amount">${formatNum(u.amount)}원</td>
              <td><select class="unmatched-target"><option value="">— 넣지 않음 —</option>${options}</select></td>
            </tr>`).join('')}
        </tbody>
      </table>
      <div class="import-actions"><button type="button" id="apply-unmatched">선택한 거래처 표에 반영</button></div>
    </div>` : ''

  // 파일의 이름과 서버 법인명이 다른 건은 접어서 보여준다('기타' → '기타법인' 처럼
  // 서버가 이어준 것을 사용자가 확인할 수 있어야 한다).
  const a10Total = (result.stats && result.stats.article10_total) || 0
  const a10Block = a10Total
    ? `<div class="hint" style="margin-top:4px">제10항 과세제외액 <strong>${formatNum(a10Total)}원</strong>도 함께 넣었습니다.</div>`
    : ''
  const renamed = (result.matched || [])
    .filter(m => (m.sources || []).some(s => s !== m.company))
  const renamedBlock = renamed.length ? `
    <details style="margin-top:10px">
      <summary style="cursor:pointer;font-size:13px;color:var(--brand-dark)">파일과 이름이 다르게 연결된 ${renamed.length}건 확인</summary>
      <table class="unmatched-table">
        <thead><tr><th>파일의 거래처명</th><th>연결된 법인</th><th style="text-align:right">매출액</th></tr></thead>
        <tbody>
          ${renamed.map(m => `<tr>
            <td>${escapeHtml(m.sources.join(', '))}</td>
            <td>${escapeHtml(m.company)}</td>
            <td class="amount">${formatNum(m.amount)}원</td>
          </tr>`).join('')}
        </tbody>
      </table>
    </details>` : ''

  box.className = 'import-report'
  box.style.display = 'block'
  box.innerHTML = `
    <h5>엑셀 반영 완료</h5>
    <div>거래처 <strong>${stats.matched_count || 0}건</strong>을 표에 넣었습니다. 합계 <strong>${formatNum(stats.matched_total || 0)}원</strong>.</div>
    <div class="hint" style="margin-top:4px">표 전체를 파일 내용으로 바꿨습니다. 파일에 없던 거래처는 0 입니다.</div>
    ${a10Block}
    ${warnings}
    ${renamedBlock}
    ${unmatchedBlock}
    <div class="import-actions"><button type="button" id="undo-import" class="secondary">업로드 전으로 되돌리기</button></div>
  `
}

document.getElementById('template-download')?.addEventListener('click', async ()=>{
  if(!token){ setImportStatus('로그인 후 이용할 수 있습니다.'); return }
  setImportStatus('양식을 준비하는 중…')
  try{
    // 거래처 목록은 연도마다 다를 수 있으므로 양식도 연도를 따라간다.
    const res = await fetch(`/api/related-sales/template${yearQuery()}`,
                            {headers:{Authorization:'Bearer '+token}})
    if(!res.ok) throw new Error(`서버 오류 (${res.status})`)
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = currentYear ? `특수관계자_세부매출_양식_${currentYear}.xlsx`
                             : '특수관계자_세부매출_양식.xlsx'
    document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url)
    setImportStatus('양식을 내려받았습니다. B열 금액만 채워서 다시 올려주세요.')
  }catch(e){
    setImportStatus(`양식을 받지 못했습니다: ${e.message}`)
  }
})

document.getElementById('excel-upload-button')?.addEventListener('click', ()=>{
  if(!token){ setImportStatus('로그인 후 이용할 수 있습니다.'); return }
  $('excel-upload-input')?.click()
})

document.getElementById('excel-upload-input')?.addEventListener('change', async (e)=>{
  const file = e.target.files && e.target.files[0]
  // 같은 파일을 고쳐서 다시 올릴 수 있어야 하므로 값을 비워 change 가 또 걸리게 한다.
  e.target.value = ''
  if(!file) return
  setImportStatus(`${file.name} 읽는 중…`)
  const box = $('import-report')
  if(box) box.style.display = 'none'
  try{
    const form = new FormData()
    form.append('file', file)
    // Content-Type 은 직접 넣지 않는다. 브라우저가 multipart 경계값을 붙여야 한다.
    const res = await fetch(`/api/related-sales/import${yearQuery()}`, {
      method: 'POST', headers: {Authorization:'Bearer '+token}, body: form
    })
    // 413 은 nginx 가 백엔드에 닿기도 전에 막은 것이라 본문이 JSON 이 아니라 HTML 이다.
    // 그대로 두면 '서버 오류 (413)' 만 뜨고 사용자는 뭘 해야 할지 알 수 없다.
    if(res.status === 413){
      throw new Error('파일이 너무 커서 서버가 받지 못했습니다. 필요한 기간·거래처만 남겨 다시 올리거나 관리자에게 문의하세요.')
    }
    const data = await res.json().catch(()=>null)
    if(!res.ok) throw new Error((data && data.detail) || `서버 오류 (${res.status})`)

    relatedSnapshot = snapshotRelated()
    lastImport = data
    const amounts = {}
    ;(data.matched || []).forEach(m => { amounts[m.company] = {amount: m.amount, article10: m.article10 || 0} })
    applyRelatedAmounts(amounts, {reset: true})
    renderImportReport(data)
    setImportStatus(`${file.name} 반영됨`)
  }catch(err){
    showImportError(err.message || '알 수 없는 오류')
    setImportStatus('')
  }
})

// 리포트는 업로드할 때마다 다시 그려지므로 버튼에 직접 걸지 않고 위임한다.
document.getElementById('import-report')?.addEventListener('click', (e)=>{
  if(e.target && e.target.id === 'undo-import'){
    if(!relatedSnapshot) return
    applyRelatedAmounts(relatedSnapshot)
    relatedSnapshot = null
    lastImport = null
    const box = $('import-report')
    if(box){ box.style.display = 'none'; box.innerHTML = '' }
    setImportStatus('업로드 전 상태로 되돌렸습니다.')
    return
  }
  if(e.target && e.target.id === 'apply-unmatched'){
    const unmatched = (lastImport && lastImport.unmatched) || []
    let applied = 0
    document.querySelectorAll('#import-report tr[data-unmatched-index]').forEach(tr=>{
      const select = tr.querySelector('.unmatched-target')
      const target = select && select.value
      if(!target) return
      const item = unmatched[Number(tr.dataset.unmatchedIndex)]
      if(!item) return
      if(addRelatedAmount(target, item.amount)){
        applied += 1
        // 두 번 눌러 금액이 두 배가 되는 사고를 막는다.
        tr.remove()
      }
    })
    setImportStatus(applied ? `미매칭 ${applied}건을 표에 더했습니다.` : '연결할 법인을 먼저 고르세요.')
  }
})

$('evaluate').onclick = async ()=>{
  if($('form-error')) $('form-error').textContent = ''
  // validation
  try{
    const related = getRelatedFromTable()
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

    const tax_adjustments = getTaxFromTable()

    const body = {
      company, year: currentYear,
      operating_income, corporate_tax, total_sales, related_sales: related, tax_adjustments,
      article10_exclusions: getArticle10FromTable(),
      dividend_income: getDividendFromTable(),
      distributable_income: Number($('distributable_income')?.value || 0)
    }
    const reviewPath = myCompany && myCompany.company === 'admin' ? '/api/admin/evaluate-review' : '/api/evaluate'
    const r = await post(reviewPath, body)
    if(r && typeof r === 'object' && r.company && r.reason) {
      // 기업 구분은 서버가 판정한 값(r.size)이 정본이다. 화면 선택값은 응답이 없을 때만 쓴다.
      lastReviewInput = {company, year: r.year || currentYear, companySize: r.size || $('company_size').value, operating_income, corporate_tax, total_sales, related, tax_adjustments}
      const isAdmin = myCompany && myCompany.company === 'admin'
      renderReport(r, {...lastReviewInput, isAdmin})
      $('rawdata-button').style.display = isAdmin ? 'inline-block' : 'none'
      $('input-page').style.display = 'none'
      $('result-page').style.display = 'block'
    } else {
      showError('서버 응답을 확인하세요')
    }
  } catch(e){ showError(e.message || '서버 응답을 확인하세요'); }
}

$('back-to-input').onclick = ()=>{
  $('result-page').style.display = 'none'
  $('input-page').style.display = ''
  if($('form-error')) $('form-error').textContent = ''
}

$('rawdata-button').onclick = ()=>{
  if(!myCompany || myCompany.company !== 'admin' || !lastReviewInput) return
  renderRawData(lastReviewInput)
  $('result-page').style.display = 'none'
  $('rawdata-page').style.display = 'block'
}

$('rawdata-back').onclick = ()=>{
  $('rawdata-page').style.display = 'none'
  $('result-page').style.display = 'block'
}

function renderRawData(input){
  const rows = Object.entries(input.related || {}).map(([name, amount]) => `<tr><td>${escapeHtml(name)}</td><td style="text-align:right">${formatNum(amount)}원</td></tr>`).join('')
  const taxRows = Object.entries(input.tax_adjustments || {}).map(([name, amount]) => `<tr><td>${escapeHtml(name)}</td><td style="text-align:right">${formatNum(amount)}원</td></tr>`).join('')
  $('rawdata-content').innerHTML = `
    <div class="report-note"><strong>관리자 RAWDATA</strong><br>이번 검토 요청에 입력되어 서버로 전송된 원본 입력값입니다. 서버의 지분율·주주별 원본 데이터는 보안상 표시하지 않습니다.</div>
    <section class="report-section"><h3>기본정보</h3><table class="raw-table"><tbody>
      <tr><th>법인명</th><td>${escapeHtml(input.company)}</td></tr>
      <tr><th>기업 구분</th><td>${escapeHtml(input.companySize || '')}</td></tr>
      <tr><th>검토 연도</th><td>${escapeHtml(input.year || '')}</td></tr>
      <tr><th>총매출</th><td style="text-align:right">${formatNum(input.total_sales)}원</td></tr>
      <tr><th>영업이익</th><td style="text-align:right">${formatNum(input.operating_income)}원</td></tr>
      <tr><th>법인세 상당액</th><td style="text-align:right">${formatNum(input.corporate_tax)}원</td></tr>
    </tbody></table></section>
    <section class="report-section"><h3>특수관계자 세부매출 원본</h3><table class="raw-table"><thead><tr><th>거래처명</th><th>매출액</th></tr></thead><tbody>${rows || '<tr><td colspan="2">입력된 내역이 없습니다.</td></tr>'}</tbody></table></section>
    <section class="report-section"><h3>세무조정내역 원본</h3><table class="raw-table"><thead><tr><th>조정 항목</th><th>금액</th></tr></thead><tbody>${taxRows || '<tr><td colspan="2">입력된 내역이 없습니다.</td></tr>'}</tbody></table></section>
  `
}

$('result-back-to-input').onclick = ()=> $('back-to-input').click()

function formatNum(n){ if(n===undefined || n===null) return '—'; if(typeof n==='number') return n.toLocaleString(); try{ return Number(n).toLocaleString() }catch(e){ return String(n) }}

function renderReport(r, input){
  const el = $('result')
  const judgment = r.reason || r.judgement || r.summary || '판정 결과 없음'
  const isTaxable = Boolean(r.taxable || r.gift_tax_total > 0)
  const relatedTotal = Number(r.related_sales_total || 0)
  const relatedRatio = Number(r.related_sales_ratio || 0)
  const normalRatio = Number(r.normal_ratio || 0)
  const relatedRows = Object.entries(input.related || {}).map(([name, amount]) => `
    <tr><td>${escapeHtml(name)}</td><td class="amount">${formatNum(amount)}원</td></tr>`).join('')
  const taxRows = Object.entries(input.tax_adjustments || {}).map(([name, amount]) => `
    <tr><td>${escapeHtml(name)}</td><td class="amount">${formatNum(amount)}원</td></tr>`).join('')
  const emptyRow = '<tr><td colspan="2" class="muted">입력된 내역이 없습니다.</td></tr>'
  const pct = v => `${(Number(v) * 100).toFixed(2)}%`
  // ⑩·§18 은 주주 무관하게 100% 라 지분율 정보가 없으므로 금액을 그대로 보여준다.
  // ⑭ 지분율 상당액은 (금액 ÷ 매출액) 으로 지분율이 역산되므로 일반 응답에는 거래처별 값도
  // 합계도 오지 않는다. 범위(rate_min/max)와 합계는 관리자 응답에만 실린다.
  const exclusionList = r.exclusion_details || []
  const exclusionRows = exclusionList.map(d => {
    let rate, amount
    if(d.rate !== null && d.rate !== undefined){
      rate = pct(d.rate)
      amount = `${formatNum(d.excluded_sales)}원`
    } else if(d.rate_min !== undefined){
      rate = `${pct(d.rate_min)} ~ ${pct(d.rate_max)}`
      amount = `${formatNum(d.excluded_sales_min)}원 ~ ${formatNum(d.excluded_sales_max)}원`
    } else {
      rate = '<span class="muted">주주별 상이</span>'
      amount = '<span class="muted">비공개</span>'
    }
    return `<tr><td>${escapeHtml(d.counterparty)}</td><td class="amount">${formatNum(d.sales)}원</td><td>${escapeHtml(d.reason)}</td><td>${escapeHtml(d.article)}</td><td class="amount">${rate}</td><td class="amount">${amount}</td></tr>`
  }).join('')
  const hasRatioRows = exclusionList.some(d => d.rate === null || d.rate === undefined)
  // 합계도 관리자 전용이다. 일반 응답에 실으면 거래처를 1건만 넣어 호출하거나 요청을 쪼개
  // 차분을 내는 것만으로 (합계 ÷ 매출액) = 지배주주 지분율이 그대로 복원된다.
  const ratioTotalRow = !hasRatioRows ? ''
    : (input.isAdmin && r.ratio_exclusion_total_max !== undefined
      ? `<tr class="total-row"><th colspan="5">⑭ 지분율 상당액 합계</th><td class="amount">${formatNum(r.ratio_exclusion_total_min)}원 ~ ${formatNum(r.ratio_exclusion_total_max)}원</td></tr>`
      : `<tr class="total-row"><th colspan="5">⑭ 지분율 상당액 합계</th><td class="amount muted">비공개 (지분율 역산 방지)</td></tr>`)
  const emptyExclusionRow = '<tr><td colspan="6" class="muted">입력된 특수관계자 매출이 없습니다.</td></tr>'
  const taxTotal = Object.values(input.tax_adjustments || {}).reduce((sum, v) => sum + (Number(v) || 0), 0)
  const taxTotalRow = taxRows ? `<tr class="total-row"><th>합계 (영업이익 가감액)</th><td class="amount">${formatNum(taxTotal)}원</td></tr>` : ''
  const adminLogic = input.isAdmin ? `
    <section class="logic-box"><h3>관리자용 계산 로직 검토</h3>
      <ol>
        <li>선택한 법인의 기업 구분에 따라 정상 거래 비율과 보유 요건 기준을 서버에서 적용합니다.</li>
        <li>입력한 특수관계자 매출을 합산하고 총매출 대비 특수관계 매출 비율을 계산합니다.</li>
        <li>세무조정 후 영업이익과 법인세 상당액을 반영해 과세 검토 대상 금액을 산출합니다.</li>
        <li>서버에 보관된 지분·관계 데이터를 적용해 증여의제 금액을 계산합니다.</li>
        <li>증여의제 금액에 누진세율을 적용해 산출 증여세와 과세 여부를 판정합니다.</li>
      </ol>
      <div class="logic-formula"><strong>검토 산식 요약</strong><br>
        특수관계 매출 비율 = 특수관계 매출 합계 ÷ 총매출<br>
        증여의제 금액 = 세후 영업이익 × 조정 비율 × 보유 요건 반영값<br>
        산출 증여세 = 증여의제 금액(배당소득 공제 후)에 세율 및 누진공제 적용<br>
        납부 증여세 = 산출 증여세 − 신고세액공제 3% (10원 미만 절사)<br>
        <span class="muted">※ 아래 주주별 상세(실명·지분율)는 관리자 인증에서만 노출됩니다. 일반 사용자 화면과 RAWDATA 화면에는 표시되지 않습니다.</span>
      </div>
      <div class="report-section" style="overflow:auto"><h3>주주별 계산 상세</h3>
        <table class="report-table detail-table"><thead><tr><th>구분</th><th>지분율</th><th>과세제외매출</th><th>제외 후 특수관계 매출 비율</th><th>세후 영업이익</th><th>증여의제이익</th><th>배당소득 공제</th><th>산출 증여세</th><th>신고세액공제</th><th>납부 증여세</th><th>판정</th></tr></thead><tbody>
          ${(r.shareholder_details || []).map(detail => `<tr><td>${escapeHtml(detail.code)}</td><td class="amount">${(Number(detail.holding_ratio) * 100).toFixed(2)}%</td><td class="amount">${formatNum(detail.excluded_sales)}원</td><td class="amount">${(Number(detail.adjusted_related_ratio) * 100).toFixed(2)}%</td><td class="amount">${formatNum(detail.after_tax_operating_income)}원</td><td class="amount">${formatNum(detail.deemed_gift_income)}원</td><td class="amount">${formatNum(detail.dividend_deduction || 0)}원</td><td class="amount">${formatNum(detail.gift_tax)}원</td><td class="amount">${formatNum(detail.filing_credit || 0)}원</td><td class="amount"><strong>${formatNum(detail.gift_tax_payable || 0)}원</strong></td><td>${detail.taxable ? '<span class="report-status yes">대상</span>' : '<span class="report-status no">비대상</span>'}</td></tr>`).join('')}
          <tr class="total-row"><th colspan="5">총합</th><td class="amount">${formatNum(r.deemed_gift_total)}원</td><td class="amount">${formatNum(r.dividend_deduction_total || 0)}원</td><td class="amount">${formatNum(r.gift_tax_total)}원</td><td class="amount">${formatNum(r.filing_credit_total || 0)}원</td><td class="amount"><strong>${formatNum(r.gift_tax_payable_total || 0)}원</strong></td><td></td></tr>
        </tbody></table>
        <div class="hint">관리자 인증에서만 표시되는 상세값입니다.</div>
      </div>
    </section>` : ''

  el.innerHTML = `
    <div class="report-note"><span class="report-status ${isTaxable ? 'yes' : 'no'}">${isTaxable ? '과세대상' : '해당없음'}</span><div style="margin-top:8px">${escapeHtml(judgment)}</div></div>

    <section class="report-section"><h3>1. 기본정보</h3>
      <table class="report-table"><tbody>
        <tr><th>법인명</th><td>${escapeHtml(input.company)}</td></tr>
        <tr><th>기업 구분</th><td>${escapeHtml(input.companySize || '미입력')}</td></tr>
        <tr><th>검토 연도</th><td>${escapeHtml(r.year || '')}${r.data_as_of ? ` <span class="muted">(${escapeHtml(r.data_as_of)})</span>` : ''}</td></tr>
        <tr><th>총매출</th><td class="amount">${formatNum(input.total_sales)}원</td></tr>
        <tr><th>영업이익</th><td class="amount">${formatNum(input.operating_income)}원</td></tr>
        <tr><th>법인세 상당액</th><td class="amount">${formatNum(input.corporate_tax)}원</td></tr>
      </tbody></table>
    </section>

    <section class="report-section"><h3>2. 판정 요건 및 계산 결과</h3>
      <table class="report-table"><tbody>
        <tr><th>특수관계자 매출 합계</th><td class="amount">${formatNum(relatedTotal)}원</td></tr>
        <tr><th>특수관계자 매출 비율</th><td class="amount">${(relatedRatio * 100).toFixed(1)}%</td></tr>
        <tr><th>정상 거래 비율</th><td class="amount">${(normalRatio * 100).toFixed(1)}%</td></tr>
        ${input.isAdmin ? `<tr><th>과세제외매출(공통)¹</th><td class="amount">${formatNum(r.excluded_sales_common)}원</td></tr>
        <tr><th>과세제외매출(계산 범위)²</th><td class="amount">${formatNum(r.excluded_sales_min)}원 ~ ${formatNum(r.excluded_sales_max)}원</td></tr>
        <tr><th>제외 후 특수관계 매출 비율</th><td class="amount">${(r.adjusted_related_ratio_min * 100).toFixed(1)}% ~ ${(r.adjusted_related_ratio_max * 100).toFixed(1)}%</td></tr>` : ''}
        <tr><th>증여의제 금액</th><td class="amount">${formatNum(r.deemed_gift_total)}원</td></tr>
        ${r.dividend_deduction_total ? `<tr><th>배당소득 공제</th><td class="amount">-${formatNum(r.dividend_deduction_total)}원</td></tr>` : ''}
        <tr><th>산출 증여세</th><td class="amount">${formatNum(r.gift_tax_total)}원</td></tr>
        <tr><th>신고세액공제 (3%)</th><td class="amount">-${formatNum(r.filing_credit_total || 0)}원</td></tr>
        <tr><th>납부 증여세</th><td class="amount"><strong>${formatNum(r.gift_tax_payable_total || 0)}원</strong></td></tr>
      </tbody></table>
      ${input.isAdmin ? '<div class="hint">¹ 제10항 기준으로 공통 제외된 매출입니다. ² 서버의 민감한 지분 계산을 집계한 범위이며 원본 비율은 표시하지 않습니다.</div>' : ''}
    </section>

    <section class="report-section"><h3>3. 특수관계자 세부매출</h3>
      <table class="report-table"><thead><tr><th>거래처명</th><th>매출액</th></tr></thead><tbody>${relatedRows || emptyRow}</tbody></table>
    </section>

    <section class="report-section"><h3>4. 과세제외 내역</h3>
      <div style="overflow:auto">
        <table class="report-table exclusion-table"><thead><tr><th>거래처명</th><th>매출액</th><th>과세제외 사유</th><th>적용 조문</th><th>적용률</th><th>과세제외매출액</th></tr></thead><tbody>${exclusionRows || emptyExclusionRow}${ratioTotalRow}</tbody></table>
      </div>
      <div class="hint">⑩ 기본 과세제외를 먼저 판정하고, 해당하지 않는 거래처만 ⑭ 추가 과세제외를 적용합니다. 사유가 겹치면 합산하지 않고 과세제외금액이 가장 큰 하나만 적용합니다. ⑭ 지분율 상당액은 지배주주마다 적용률이 달라 ${input.isAdmin ? '최소~최대 범위로 표시하며, 주주별 상세는 아래 관리자 검토 항목을 참고하세요.' : '거래처별 값 대신 합계 범위로 표시합니다.'}</div>
    </section>

    <section class="report-section"><h3>5. 세무조정내역</h3>
      <table class="report-table"><thead><tr><th>조정 항목</th><th>금액</th></tr></thead><tbody>${taxRows || emptyRow}${taxTotalRow}</tbody></table>
      <div class="hint">세후영업이익 = 영업이익 ± 세무조정금액 − 법인세 상당액</div>
    </section>

    ${adminLogic}
  `
}

// 속성값 안에도 삽입되므로(data-company="...") 따옴표까지 이스케이프한다.
function escapeHtml(s){
  return String(s === undefined || s === null ? '' : s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;').replace(/'/g,'&#39;')
}
